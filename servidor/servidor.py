import paho.mqtt.client as mqtt
import struct
import time

# ==== Configurações ====
BROKER_IP = "192.168.0.123"  # Coloque o IP do seu PC aqui
TOPIC_CMD = "exame/comando"
TOPIC_STATUS = "exame/status"
TOPIC_DADOS = "exame/dados"

# ==== Funções de Callback MQTT ====
def on_connect(client, userdata, flags, rc):
    print(f"Conectado ao Broker MQTT (Código: {rc})")
    # Assina os tópicos para ouvir o que o ESP32 fala
    client.subscribe(TOPIC_STATUS)
    client.subscribe(TOPIC_DADOS)
    
    # Dá um tempozinho e envia o gatilho inicial
    print("Enviando comando de INICIAR_1 para o ESP32...")
    time.sleep(1)
    client.publish(TOPIC_CMD, "INICIAR_1")

def on_message(client, userdata, msg):
    # Se a mensagem for no tópico de STATUS
    if msg.topic == TOPIC_STATUS:
        print(f"[STATUS DO ESP32]: {msg.payload.decode()}")
        
    # Se a mensagem for no tópico de DADOS
    elif msg.topic == TOPIC_DADOS:
        # Cada amostra tem 12 bytes (3 floats de 4 bytes: X, Y, Z)
        num_amostras = len(msg.payload) // 12
        print(f"[PACOTE RECEBIDO]: {num_amostras} amostras.")
        
        # Vamos desempacotar apenas a PRIMEIRA amostra desse pacote para testar
        if num_amostras > 0:
            # '<fff' significa: decodifique como Little-Endian, 3 floats
            amostra = struct.unpack('<fff', msg.payload[:12])
            print(f"   -> Amostra Desempacotada - Pitch(X): {amostra[0]:.2f} | Roll(Y): {amostra[1]:.2f} | Yaw(Z): {amostra[2]:.2f}")

# ==== Inicialização do Cliente ====
# Usa a versão antiga da API para evitar warnings de versão no Paho
client = mqtt.Client() 
client.on_connect = on_connect
client.on_message = on_message

print("Conectando ao Broker...")
client.connect(BROKER_IP, 1883, 60)

# Mantém o script rodando e escutando
client.loop_forever()