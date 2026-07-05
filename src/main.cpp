#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <math.h>

// ==== Configurações de Rede e MQTT ====
const char* ssid = "rededoprojeto";
const char* password = "arededoprojeto";
const char* mqtt_server = "192.168.0.122"; // Coloque o IP do seu PC aqui

WiFiClient espClient;
PubSubClient client(espClient);

// ==== Endereço I2C do MPU (Confirmado pelo seu Scanner) ====
const int MPU_ADDR = 0x68;

// ==== Variáveis do Sistema ====
const unsigned long SENSOR_INTERVAL = 5; // 5ms (200Hz)
const int TOTAL_SAMPLES = 3000;          // 15 segundos / 5ms = 3000 amostras
unsigned long lastTime = 0;              // Para o delta tempo do Kalman

struct Sample {
  float x;
  float y;
  float z;
};

Sample buffer[TOTAL_SAMPLES];

enum State { WAITING, RECORDING, SENDING };
State currentState = WAITING;

// ==== Estruturas de Kalman ====
typedef struct {
  float Q_angle, Q_bias, R_measure;
  float angle, bias, rate;
  float P[2][2];
} Kalman;

Kalman kalmanX, kalmanY, kalmanZ;
float angX = 0, angY = 0, angZ = 0;

void initKalman(Kalman &K) {
  K.Q_angle = 0.001; K.Q_bias = 0.003; K.R_measure = 0.03;
  K.angle = 0; K.bias = 0;
  K.P[0][0] = 0; K.P[0][1] = 0; K.P[1][0] = 0; K.P[1][1] = 0;
}

float kalmanUpdate(Kalman &K, float newAngle, float newRate, float dt) {
  K.rate = newRate - K.bias;
  K.angle += dt * K.rate;
  K.P[0][0] += dt * (dt * K.P[1][1] - K.P[0][1] - K.P[1][0] + K.Q_angle);
  K.P[0][1] -= dt * K.P[1][1];
  K.P[1][0] -= dt * K.P[1][1];
  K.P[1][1] += K.Q_bias * dt;

  float S = K.P[0][0] + K.R_measure;
  float K_gain[2];
  K_gain[0] = K.P[0][0] / S;
  K_gain[1] = K.P[1][0] / S;

  float y = newAngle - K.angle;
  K.angle += K_gain[0] * y;
  K.bias += K_gain[1] * y;

  float P00_temp = K.P[0][0];
  float P01_temp = K.P[0][1];

  K.P[0][0] -= K_gain[0] * P00_temp;
  K.P[0][1] -= K_gain[0] * P01_temp;
  K.P[1][0] -= K_gain[1] * P00_temp;
  K.P[1][1] -= K_gain[1] * P01_temp;

  return K.angle;
}

// ==========================
// Leitura Direta dos Registradores I2C
// ==========================
void readSensor_filtered() {
  // Aponta para o registrador 0x3B (Início dos dados do Acelerômetro)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  
  // Solicita 14 bytes (6 do Accel, 2 da Temperatura, 6 do Gyro)
  Wire.requestFrom(MPU_ADDR, 14, true);

  if (Wire.available() >= 14) {
    int16_t ax_raw = Wire.read() << 8 | Wire.read();
    int16_t ay_raw = Wire.read() << 8 | Wire.read();
    int16_t az_raw = Wire.read() << 8 | Wire.read();
    int16_t temp   = Wire.read() << 8 | Wire.read(); // Ignorado
    int16_t gx_raw = Wire.read() << 8 | Wire.read();
    int16_t gy_raw = Wire.read() << 8 | Wire.read();
    int16_t gz_raw = Wire.read() << 8 | Wire.read();

    unsigned long now = micros();
    float dt = (now - lastTime) / 1000000.0;
    lastTime = now;
    if (dt <= 0) return;

    // Converte escala padrão do acelerômetro (+/- 2g -> 16384 LSB/g)
    float ax = ax_raw / 16384.0;
    float ay = ay_raw / 16384.0;
    float az = az_raw / 16384.0;

    // Converte escala padrão do giroscópio (+/- 250°/s -> 131 LSB/°/s)
    float gyroRollRate  = gx_raw / 131.0;
    float gyroPitchRate = gy_raw / 131.0;
    float gyroYawRate   = gz_raw / 131.0;

    // Ângulos do acelerômetro
    float accelRoll  = atan2(ay, az) * 180 / PI;
    float accelPitch = atan(-ax / sqrt(ay * ay + az * az)) * 180 / PI;

    // Filtro de Kalman Aplicado
    angX = kalmanUpdate(kalmanX, accelPitch, gyroPitchRate, dt);
    angY = kalmanUpdate(kalmanY, accelRoll, gyroRollRate, dt);
    angZ = kalmanUpdate(kalmanZ, angZ, gyroYawRate, dt); 
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg = "";
  for (int i = 0; i < length; i++) msg += (char)payload[i];
  
  Serial.print("Comando recebido: ");
  Serial.println(msg);

  if (msg.startsWith("INICIAR") && currentState == WAITING) {
    currentState = RECORDING;
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Tentando conexao MQTT...");
    if (client.connect("ESP32_Tremores")) {
      Serial.println("Conectado!");
      client.subscribe("exame/comando");
      client.publish("exame/status", "AGUARDANDO_COMANDO");
    } else {
      Serial.print("Falhou, rc=");
      Serial.print(client.state());
      Serial.println(" Tentando novamente em 5s");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(); 

  // Conexão Wi-Fi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi conectado.");

  // ==== INICIALIZAÇÃO NATIVA DO MPU ====
  Serial.println("Acordando o sensor MPU...");
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B); // Registrador PWR_MGMT_1
  Wire.write(0);    // Envia 0 para tirar o chip do modo de hibernação (Sleep)
  byte error = Wire.endTransmission(true);

  if (error != 0) {
    Serial.println("Erro crítico ao inicializar registradores do MPU!");
    while (1) delay(10);
  }
  Serial.println("Sensor MPU ativo e operando em modo direto.");

  // Configuração MQTT
  client.setServer(mqtt_server, 1883);
  client.setCallback(mqttCallback);
  client.setBufferSize(512); 

  initKalman(kalmanX); initKalman(kalmanY); initKalman(kalmanZ);
  Serial.println("Sistema Pronto.");
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  
  if (currentState != RECORDING) {
    client.loop(); 
  }

  // ==== ESTADO: GRAVANDO ====
  if (currentState == RECORDING) {
    client.publish("exame/status", "GRAVANDO");
    Serial.println("Gravando 15s...");
    
    int sampleIndex = 0;
    unsigned long startRecordTime = millis();
    unsigned long lastSampleMillis = 0;
    lastTime = micros(); 

    while (millis() - startRecordTime < 15000 && sampleIndex < TOTAL_SAMPLES) {
      unsigned long currentMillis = millis();
      
      if (currentMillis - lastSampleMillis >= SENSOR_INTERVAL) {
        lastSampleMillis = currentMillis;
        
        readSensor_filtered();
        
        buffer[sampleIndex].x = angX;
        buffer[sampleIndex].y = angY;
        buffer[sampleIndex].z = angZ;
        sampleIndex++;
      }
      yield(); 
    }
    
    Serial.println("Gravacao concluida!");
    currentState = SENDING;
  }

  // ==== ESTADO: ENVIANDO ====
  if (currentState == SENDING) {
    client.publish("exame/status", "ENVIANDO_DADOS");
    Serial.println("Enviando dados via MQTT...");

    int samplesPerChunk = 20; 
    
    for (int i = 0; i < TOTAL_SAMPLES; i += samplesPerChunk) {
      int chunkSamples = min(samplesPerChunk, TOTAL_SAMPLES - i);
      int byteLength = chunkSamples * sizeof(Sample);
      
      client.publish("exame/dados", (uint8_t*)&buffer[i], byteLength);
      delay(10); 
    }
    
    client.publish("exame/status", "LOTE_CONCLUIDO");
    Serial.println("Lote concluído. Aguardando próximo comando.");
    currentState = WAITING;
  }
}