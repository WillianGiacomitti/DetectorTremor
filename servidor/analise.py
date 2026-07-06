import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.fft import rfft, rfftfreq

# ==== CONFIGURAÇÕES ====
# Coloque aqui o nome do arquivo CSV gerado pelo seu controlador
# ARQUIVO_CSV = r"C:\Users\Will\Documents\PlatformIO\Projects\DetectorTremor\exame_tremores_2026-07-04_21-17-55.csv"
ARQUIVO_CSV = r"C:\Users\Will\Documents\PlatformIO\Projects\DetectorTremor\exame_tremores_2026-07-06_10-56-40.csv"
# ARQUIVO_CSV = r"C:\Users\Will\Documents\PlatformIO\Projects\DetectorTremor\exame_tremores_2026-07-04_21-22-27.csv" 
TAXA_AMOSTRAGEM = 200.0  # O nosso ESP32 coleta a 200 Hz (5ms)

def analisar_dados():
    print(f"Carregando dados de: {ARQUIVO_CSV}")
    try:
        df = pd.read_csv(ARQUIVO_CSV)
    except FileNotFoundError:
        print("Erro: Arquivo CSV não encontrado. Verifique o nome!")
        return

    # Cria um eixo de tempo real baseado na nossa taxa de amostragem
    # Se temos 3000 amostras a 200 Hz, teremos 15 segundos de dados.
    numero_amostras = len(df)
    tempo = np.arange(numero_amostras) / TAXA_AMOSTRAGEM

    # Removemos a média de cada eixo (DC Offset) para centralizar os gráficos no zero.
    # Isso é essencial para o cálculo correto da Frequência.
    pitch_limpo = df['Pitch_X'] - df['Pitch_X'].mean()
    roll_limpo = df['Roll_Y'] - df['Roll_Y'].mean()
    yaw_limpo = df['Yaw_Z'] - df['Yaw_Z'].mean()

    # ==== CÁLCULO DA FFT (Fast Fourier Transform) ====
    # A FFT converte o sinal de tempo em frequências (Hz)
    frequencias = rfftfreq(numero_amostras, 1 / TAXA_AMOSTRAGEM)
    
    # Calculamos a magnitude (força) de cada frequência
    fft_pitch = np.abs(rfft(pitch_limpo))
    fft_roll = np.abs(rfft(roll_limpo))
    fft_yaw = np.abs(rfft(yaw_limpo))

    # ==== PLOTAGEM DOS GRÁFICOS ====
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    fig.canvas.manager.set_window_title('Análise de Tremor - MPU9250')

    # 1. Gráfico no Domínio do Tempo (A amplitude do movimento)
    ax1.plot(tempo, pitch_limpo, label='Pitch (X)', alpha=0.8)
    ax1.plot(tempo, roll_limpo, label='Roll (Y)', alpha=0.8)
    ax1.plot(tempo, yaw_limpo, label='Yaw (Z)', alpha=0.8)
    ax1.set_title('Domínio do Tempo - Amplitude do Tremor', fontsize=14)
    ax1.set_xlabel('Tempo (Segundos)')
    ax1.set_ylabel('Amplitude (Graus)')
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend()

    # 2. Gráfico no Domínio da Frequência (A velocidade do tremor)
    ax2.plot(frequencias, fft_pitch, label='Freq. Pitch (X)')
    ax2.plot(frequencias, fft_roll, label='Freq. Roll (Y)')
    ax2.plot(frequencias, fft_yaw, label='Freq. Yaw (Z)')
    ax2.set_title('Domínio da Frequência (FFT) - Identificação do Tremor', fontsize=14)
    ax2.set_xlabel('Frequência (Hz)')
    ax2.set_ylabel('Magnitude')
    ax2.set_xlim(0, 25) # Limitamos a 25 Hz porque tremores humanos não passam disso
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    analisar_dados()