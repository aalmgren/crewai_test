# GeoAI Web Interface

Interface web para análise de dados de sondagem usando CrewAI.

## Estrutura

- `index.html` - Interface web (GitHub Pages)
- `style.css` - Estilos
- `app.js` - JavaScript para drag-and-drop e comunicação com API
- `api.py` - Backend Flask para processar arquivos
- `crewai_test.py` - Lógica de análise (modificado para suportar API)

## Setup

### Backend (Flask API)

1. Instalar dependências:
```bash
pip install -r requirements.txt
```

2. Configurar `.env` com `OPENAI_API_KEY`

3. Executar API:
```bash
python api.py
```

A API estará disponível em `http://localhost:5000`

### Frontend (GitHub Pages)

1. Fazer commit dos arquivos `index.html`, `style.css`, `app.js`

2. No GitHub, habilitar GitHub Pages nas configurações do repositório

3. Atualizar `API_URL` em `app.js` para apontar para o backend (ex: Render, Railway, etc.)

## Deploy do Backend

### Opção 1: Render.com

1. Criar novo Web Service
2. Conectar repositório GitHub
3. Build command: `pip install -r requirements.txt`
4. Start command: `python api.py`
5. Adicionar variável de ambiente `OPENAI_API_KEY`

### Opção 2: Railway

1. Criar novo projeto
2. Conectar repositório
3. Railway detecta automaticamente Python
4. Adicionar variável de ambiente `OPENAI_API_KEY`

### Opção 3: Local (desenvolvimento)

```bash
python api.py
```

## Uso

1. Acessar a página no GitHub Pages
2. Arrastar arquivos CSV para a área de upload
3. Clicar em "Analyze Files"
4. Aguardar processamento
5. Visualizar tabela consolidada

## Segurança - Token OpenAI

**IMPORTANTE**: O token da OpenAI fica APENAS no backend (servidor), nunca no frontend!

- ✅ **Backend**: O token está em variável de ambiente (`.env` ou variável do servidor)
- ✅ **Frontend**: NÃO tem acesso ao token - apenas chama o backend via HTTP
- ✅ **Usuários**: Quando alguém usa a interface, o backend usa SEU token (do servidor)
- ❌ **Nunca**: Coloque o token no JavaScript, HTML ou qualquer arquivo do frontend

### Como funciona:
1. Usuário acessa GitHub Pages (frontend)
2. Usuário faz upload de arquivos
3. Frontend envia arquivos para o backend (API)
4. Backend usa SEU token (do servidor) para processar
5. Backend retorna resultados
6. Frontend exibe resultados

**O token nunca sai do servidor!**

## Notas

- O backend precisa estar acessível publicamente para o GitHub Pages funcionar
- CORS está habilitado no Flask para permitir requisições do GitHub Pages
- A API processa arquivos em diretório temporário e retorna JSON
- O token deve ser configurado APENAS no backend (variável de ambiente)

