"""
Script para verificar quais modelos OpenAI estão disponíveis na sua conta
"""
import os
from dotenv import load_dotenv
from openai import OpenAI

# Carregar variáveis de ambiente
load_dotenv()

# Obter API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("ERRO: OPENAI_API_KEY não encontrada no arquivo .env")
    exit(1)

# Criar cliente OpenAI
client = OpenAI(api_key=api_key)

# Lista de modelos para testar (incluindo os que aparecem na sua conta)
models_to_test = [
    # Modelos básicos
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-16k",
    # Modelos GPT-4
    "gpt-4",
    "gpt-4-turbo",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-40",
    "gpt-40-realtime-preview",
    # Modelos GPT-5
    "gpt-5.1",
    "gpt-5-mini",
    "gpt-5-nano",
    # Modelos O
    "o3",
    "o4-mini",
    # Outros
    "gpt-4-1106-preview",
]

print("=" * 70)
print("VERIFICANDO MODELOS DISPONÍVEIS NA SUA CONTA")
print("=" * 70)
print()

available_models = []
unavailable_models = []

for model in models_to_test:
    try:
        print(f"Testando {model}...", end=" ")
        # Tentar fazer uma chamada simples
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "test"}
            ],
            max_tokens=5
        )
        print("✓ DISPONÍVEL")
        available_models.append(model)
    except Exception as e:
        error_msg = str(e)
        if "does not have access" in error_msg or "not found" in error_msg.lower():
            print("✗ NÃO DISPONÍVEL")
            unavailable_models.append((model, "Sem acesso"))
        else:
            print(f"✗ ERRO: {error_msg[:50]}")
            unavailable_models.append((model, error_msg[:50]))

print()
print("=" * 70)
print("RESUMO")
print("=" * 70)
print()

if available_models:
    print("✓ MODELOS DISPONÍVEIS:")
    for model in available_models:
        print(f"  - {model}")
    print()

if unavailable_models:
    print("✗ MODELOS NÃO DISPONÍVEIS:")
    for model, reason in unavailable_models:
        print(f"  - {model}: {reason}")
    print()

# Recomendação
if available_models:
    print("=" * 70)
    print("RECOMENDAÇÃO")
    print("=" * 70)
    if "gpt-4o" in available_models:
        print("✓ Use 'gpt-4o' - melhor custo-benefício e precisão")
    elif "gpt-4-turbo" in available_models:
        print("✓ Use 'gpt-4-turbo' - alta precisão")
    elif "gpt-4" in available_models:
        print("✓ Use 'gpt-4' - boa precisão")
    elif "gpt-3.5-turbo" in available_models:
        print("✓ Use 'gpt-3.5-turbo' - mais barato, mas menos preciso")
    
    print()
    print("Para usar um modelo específico, adicione no arquivo .env:")
    print(f"OPENAI_MODEL={available_models[0]}")
    print()

