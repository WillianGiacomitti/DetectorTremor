import paho.mqtt.client as mqtt
import struct
import csv
import time
from datetime import datetime

# ==== CONFIGURAÇÕES ====
BROKER_IP = "192.168.0.122"  # Coloque o IP do seu PC (o mesmo que está no ESP32)
TOPIC_COMANDO = "exame/comando"
TOPIC_STATUS = "exame/status"
TOPIC_DADOS = "exame/dados"

class SistemaExame:
    def __init__(self, broker):
        self.broker = broker
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        # Variáveis de Controle
        self.status_esp32 = "DESCONECTADO"
        self.dados_buffer = []
        self.exame_em_andamento = False

    def iniciar(self):
        print("[SISTEMA] Conectando ao Broker MQTT...")
        self.client.connect(self.broker, 1883, 60)
        self.client.loop_start() # Roda o MQTT em segundo plano

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("[SISTEMA] Conectado com sucesso ao Broker!")
            # Assina os tópicos para ouvir o ESP32
            self.client.subscribe(TOPIC_STATUS)
            self.client.subscribe(TOPIC_DADOS)
        else:
            print(f"[ERRO] Falha na conexão. Código: {rc}")

    def on_message(self, client, userdata, msg):
        # Tratamento de Status
        if msg.topic == TOPIC_STATUS:
            novo_status = msg.payload.decode('utf-8')
            self.status_esp32 = novo_status
            print(f"\n[ESP32 STATUS] -> {self.status_esp32}")
            
            # Se o ESP32 avisou que terminou, salvamos o arquivo
            if self.status_esp32 == "LOTE_CONCLUIDO":
                self.salvar_dados_csv()
                self.exame_em_andamento = False

        # Tratamento de Dados Binários
        elif msg.topic == TOPIC_DADOS:
            payload = msg.payload
            tamanho_amostra = 12  # 3 floats (x, y, z) * 4 bytes cada
            qtd_amostras = len(payload) // tamanho_amostra
            
            for i in range(qtd_amostras):
                offset = i * tamanho_amostra
                byte_chunk = payload[offset : offset + tamanho_amostra]
                
                # Desempacota os 12 bytes em 3 floats (Little-endian)
                pitch, roll, yaw = struct.unpack('<fff', byte_chunk)
                self.dados_buffer.append((pitch, roll, yaw))
            
            print(f"  -> Recebido pacote com {qtd_amostras} amostras. (Total: {len(self.dados_buffer)})", end="\r")

    def disparar_comando_iniciar(self):
        if self.status_esp32 == "AGUARDANDO_COMANDO" or self.status_esp32 == "LOTE_CONCLUIDO":
            print("\n[SISTEMA] Enviando comando para INICIAR a gravação...")
            self.dados_buffer.clear() # Limpa o buffer antigo
            self.exame_em_andamento = True
            self.client.publish(TOPIC_COMANDO, "INICIAR")
        else:
            print(f"\n[AVISO] O ESP32 não está pronto. Status atual: {self.status_esp32}")

    def salvar_dados_csv(self):
        if not self.dados_buffer:
            print("\n[AVISO] Nenhum dado para salvar.")
            return

        # Cria um nome de arquivo único com base na data e hora
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        nome_arquivo = f"exame_tremores_{timestamp}.csv"

        print(f"\n[SISTEMA] Salvando {len(self.dados_buffer)} amostras em '{nome_arquivo}'...")
        
        with open(nome_arquivo, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Amostra", "Pitch_X", "Roll_Y", "Yaw_Z"]) # Cabeçalho
            
            for index, (pitch, roll, yaw) in enumerate(self.dados_buffer):
                writer.writerow([index + 1, round(pitch, 4), round(roll, 4), round(yaw, 4)])
                
        print(f"[SISTEMA] Arquivo salvo com sucesso! Exame finalizado.")


# ==========================================
# MENU DE INTERAÇÃO COM O USUÁRIO (MÉDICO/OPERADOR)
# ==========================================
if __name__ == "__main__":
    sistema = SistemaExame(BROKER_IP)
    sistema.iniciar()

    # Aguarda um tempinho para a conexão estabelecer
    time.sleep(2)

    print("\n" + "="*40)
    print("   PAINEL DE CONTROLE - EXAME DE TREMORES")
    print("="*40)

    while True:
        try:
            # Menu simples para o operador
            if not sistema.exame_em_andamento:
                print("\nOpções:")
                print("  [1] - Iniciar novo exame (15 segundos)")
                print("  [0] - Sair do sistema")
                
                escolha = input("Digite sua escolha: ")
                
                if escolha == '1':
                    sistema.disparar_comando_iniciar()
                    # Trava o menu enquanto o exame roda
                    while sistema.exame_em_andamento:
                        time.sleep(1)
                elif escolha == '0':
                    print("\n[SISTEMA] Encerrando...")
                    sistema.client.loop_stop()
                    break
                else:
                    print("\n[AVISO] Opção inválida.")
            else:
                time.sleep(1) # Aguarda silenciosamente o fim da transmissão
                
        except KeyboardInterrupt:
            print("\n[SISTEMA] Encerrado pelo usuário.")
            sistema.client.loop_stop()
            break