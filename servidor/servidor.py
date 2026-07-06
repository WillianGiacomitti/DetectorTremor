import os
import csv
import json
import struct
import threading
from datetime import datetime
import numpy as np
import pandas as pd
from scipy.fft import rfft, rfftfreq
from flask import Flask, render_template, jsonify, request
import paho.mqtt.client as mqtt

# ==== CONFIGURAÇÕES GERAIS ====
BROKER_IP = "10.201.72.236"  # Ajuste para o IP do seu Broker/PC se necessário
TOPIC_COMANDO = "exame/comando"
TOPIC_STATUS = "exame/status"
TOPIC_DADOS = "exame/dados"
TAXA_AMOSTRAGEM = 200.0  # Hz (coleta a cada 5ms)

app = Flask(__name__, template_folder='templates')

# ==== ESTADO GLOBAL DO SISTEMA ====
class EstadoSistema:
    def __init__(self):
        self.status_esp32 = "DESCONECTADO"
        self.paciente_atual = ""
        self.dados_buffer = []
        self.exame_em_andamento = False
        self.ultimo_arquivo_salvo = ""
        self.lock = threading.Lock()

estado = EstadoSistema()

# ==== SUBSISTEMA MQTT ====
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Conectado ao broker em {BROKER_IP}")
        client.subscribe(TOPIC_STATUS)
        client.subscribe(TOPIC_DADOS)
    else:
        print(f"[MQTT ERRO] Falha na conexão. Código: {rc}")

def on_message(client, userdata, msg):
    global estado
    
    if msg.topic == TOPIC_STATUS:
        novo_status = msg.payload.decode('utf-8')
        with estado.lock:
            estado.status_esp32 = novo_status
            print(f"[MQTT STATUS] ESP32 alterou para: {estado.status_esp32}")
            
            if estado.status_esp32 == "LOTE_CONCLUIDO" and estado.exame_em_andamento:
                salvar_dados_csv()
                estado.exame_em_andamento = False

    elif msg.topic == TOPIC_DADOS:
        payload = msg.payload
        tamanho_amostra = 12  # 3 floats (x, y, z) * 4 bytes cada
        qtd_amostras = len(payload) // tamanho_amostra
        
        novos_dados = []
        for i in range(qtd_amostras):
            offset = i * tamanho_amostra
            byte_chunk = payload[offset : offset + tamanho_amostra]
            if len(byte_chunk) == tamanho_amostra:
                pitch, roll, yaw = struct.unpack('<fff', byte_chunk)
                novos_dados.append((pitch, roll, yaw))
                
        with estado.lock:
            if estado.exame_em_andamento:
                estado.dados_buffer.extend(novos_dados)

def salvar_dados_csv():
    global estado
    if not estado.dados_buffer:
        print("[SISTEMA] Buffer vazio. Nenhum arquivo gerado.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    sanitized_name = "".join([c if c.isalnum() else "_" for c in estado.paciente_atual])
    nome_arquivo = f"exame_{sanitized_name}_{timestamp}.csv"
    
    try:
        with open(nome_arquivo, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["Amostra", "Pitch_X", "Roll_Y", "Yaw_Z"])
            for index, (pitch, roll, yaw) in enumerate(estado.dados_buffer):
                writer.writerow([index + 1, round(pitch, 4), round(roll, 4), round(yaw, 4)])
        
        estado.ultimo_arquivo_salvo = nome_arquivo
        print(f"[SISTEMA] Arquivo {nome_arquivo} salvo com {len(estado.dados_buffer)} amostras.")
    except Exception as e:
        print(f"[SISTEMA ERRO] Erro ao gravar arquivo CSV: {e}")

# Inicialização da thread do Cliente MQTT
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def iniciar_mqtt():
    try:
        mqtt_client.connect(BROKER_IP, 1883, 60)
        mqtt_client.loop_forever()
    except Exception as e:
        print(f"[MQTT ERRO] Não foi possível conectar ao broker: {e}")

# ==== SUBSISTEMA DE PROCESSAMENTO DE SINAIS (DSP) ====
def processar_sinal_csv(caminho_csv):
    try:
        df = pd.read_csv(caminho_csv)
        n_amostras = len(df)
        if n_amostras < 10:
            return {"erro": "Quantidade de amostras insuficiente para processamento."}

        tempo = (np.arange(n_amostras) / TAXA_AMOSTRAGEM).tolist()

        # Remoção do DC Offset (Centralização do sinal na média zero)
        p_raw = df['Pitch_X'].values
        r_raw = df['Roll_Y'].values
        y_raw = df['Yaw_Z'].values

        p_clean = p_raw - np.mean(p_raw)
        r_clean = r_raw - np.mean(r_raw)
        y_clean = y_raw - np.mean(y_raw)

        # Cálculo de Amplitude Média Absoluta
        amp_p = float(np.mean(np.abs(p_clean)))
        amp_r = float(np.mean(np.abs(r_clean)))
        amp_y = float(np.mean(np.abs(y_clean)))

        # Contagem de cruzamentos por zero para estimativa de ciclos/picos
        picos_p = int(np.sum(np.diff(np.sign(p_clean)) != 0) // 2)
        picos_r = int(np.sum(np.diff(np.sign(r_clean)) != 0) // 2)

        # Transformada Rápida de Fourier (FFT)
        freqs = rfftfreq(n_amostras, 1 / TAXA_AMOSTRAGEM)
        fft_p = np.abs(rfft(p_clean))
        fft_r = np.abs(rfft(r_clean))
        fft_y = np.abs(rfft(y_clean))

        # Restrição do espectro visual para a faixa biológica humana (0.5 a 25 Hz)
        indices_validos = np.where((freqs >= 0.5) & (freqs <= 25))[0]
        freqs_filtradas = freqs[indices_validos]
        fft_p_filtrada = fft_p[indices_validos]
        fft_r_filtrada = fft_r[indices_validos]
        fft_y_filtrada = fft_y[indices_validos]

        # Identificação da Frequência Dominante (Maior pico de magnitude)
        idx_dom_p = np.argmax(fft_p_filtrada) if len(fft_p_filtrada) > 0 else 0
        freq_dominante_p = float(freqs_filtradas[idx_dom_p]) if len(freqs_filtradas) > 0 else 0.0
        mag_dominante_p = float(fft_p_filtrada[idx_dom_p]) if len(fft_p_filtrada) > 0 else 0.0

        idx_dom_r = np.argmax(fft_r_filtrada) if len(fft_r_filtrada) > 0 else 0
        freq_dominante_r = float(freqs_filtradas[idx_dom_r]) if len(freqs_filtradas) > 0 else 0.0

        # Subamostragem para renderização leve no HTML (Máximo de 500 pontos no gráfico)
        fator_subamostragem = max(1, n_amostras // 500)
        
        return {
            "erro": None,
            "tempo": tempo[::fator_subamostragem],
            "pitch_sinal": p_clean.tolist()[::fator_subamostragem],
            "roll_sinal": r_clean.tolist()[::fator_subamostragem],
            "yaw_sinal": y_clean.tolist()[::fator_subamostragem],
            "frequencias": freqs_filtradas.tolist(),
            "fft_pitch": fft_p_filtrada.tolist(),
            "fft_roll": fft_r_filtrada.tolist(),
            "fft_yaw": fft_y_filtrada.tolist(),
            "metricas": {
                "pitch": {
                    "freq_dominante": round(freq_dominante_p, 2),
                    "magnitude": round(mag_dominante_p, 2),
                    "amplitude_media": round(amp_p, 2),
                    "picos_detectados": picos_p
                },
                "roll": {
                    "freq_dominante": round(freq_dominante_r, 2),
                    "amplitude_media": round(amp_r, 2),
                    "picos_detectados": picos_r
                }
            }
        }
    except Exception as e:
        return {"erro": f"Falha no processamento matemático: {str(e)}"}

# ==== ROTAS DO SERVIDOR WEB ====
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    with estado.lock:
        return jsonify({
            "status_esp32": estado.status_esp32,
            "paciente_atual": estado.paciente_atual,
            "amostras_recebidas": len(estado.dados_buffer),
            "exame_em_andamento": estado.exame_em_andamento,
            "ultimo_arquivo": estado.ultimo_arquivo_salvo
        })

@app.route('/api/iniciar', methods=['POST'])
def iniciar_exame():
    global estado
    req_data = request.get_json() or {}
    nome_paciente = req_data.get("nome_paciente", "").strip()
    
    if not nome_paciente:
        return jsonify({"sucesso": False, "erro": "Nome do paciente inválido."}), 400

    with estado.lock:
        estado.paciente_atual = nome_paciente
        estado.dados_buffer.clear()
        estado.exame_em_andamento = True
        
    try:
        mqtt_client.publish(TOPIC_COMANDO, "INICIAR")
        return jsonify({"sucesso": True, "status": "Comando enviado ao ESP32."})
    except Exception as e:
        return jsonify({"sucesso": False, "erro": f"Falha ao publicar via MQTT: {e}"}), 500

@app.route('/api/resultados', methods=['GET'])
def obter_resultados():
    with estado.lock:
        arquivo = estado.ultimo_arquivo_salvo
    
    if not arquivo or not os.path.exists(arquivo):
        return jsonify({"erro": "Nenhum arquivo de exame disponível para processamento."}), 404
        
    resultados = processar_sinal_csv(arquivo)
    return jsonify(resultados)

if __name__ == "__main__":
    # Inicializa o cliente MQTT em segundo plano para não travar o Flask
    t_mqtt = threading.Thread(target=iniciar_mqtt, daemon=True)
    t_mqtt.start()
    
    # Executa o servidor Web na porta 5000
    print("[SISTEMA] Iniciando servidor Web na porta 5000... Acesse http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)