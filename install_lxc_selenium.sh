#!/bin/bash

# Script de instalação para a versão Selenium em LXC
echo "🚀 Instalação do Health Job Scraper (Selenium Edition) em LXC"
echo "==========================================================="

# Cores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Verifica se está rodando como root
if [[ $EUID -ne 0 ]]; then
   echo -e "${YELLOW}⚠️ Este script deve ser executado como root ou com sudo${NC}"
   exit 1
fi

# --- PASSO 1: Instalar Dependências do Sistema ---
echo "📦 Atualizando sistema e instalando dependências básicas..."
apt-get update
apt-get install -y python3 python3-pip python3-venv curl wget gnupg

# --- PASSO 2: Instalar Google Chrome ---
echo "🌐 Instalando Google Chrome (necessário para o Selenium)..."
if ! command -v google-chrome &> /dev/null
then
    echo "Baixando e instalando a chave do Google..."
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add -
    echo "Adicionando o repositório do Chrome..."
    sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
    apt-get update
    echo "Instalando o Chrome..."
    apt-get install -y google-chrome-stable
    echo -e "${GREEN}✅ Google Chrome instalado com sucesso.${NC}"
else
    echo -e "${GREEN}✅ Google Chrome já está instalado.${NC}"
fi

# --- PASSO 3: Configurar a Aplicação ---
APP_DIR="/opt/health-job-scraper-selenium"
APP_USER="jobscraper"

echo "👤 Criando usuário '${APP_USER}' para a aplicação..."
if ! id -u ${APP_USER} > /dev/null 2>&1; then
    useradd -m -s /bin/bash ${APP_USER}
    echo -e "${GREEN}✅ Usuário '${APP_USER}' criado.${NC}"
else
    echo -e "${GREEN}✅ Usuário '${APP_USER}' já existe.${NC}"
fi

echo "📁 Criando diretório da aplicação em ${APP_DIR}..."
mkdir -p ${APP_DIR}/logs
cp job_search_selenium.py ${APP_DIR}/
cp requirements_selenium.txt ${APP_DIR}/requirements.txt # Renomeia para o padrão
cp credentials.json ${APP_DIR}/ 2>/dev/null || echo -e "${YELLOW}⚠️ credentials.json não encontrado. Copie manualmente.${NC}"

# --- PASSO 4: Configurar Ambiente Python ---
echo "🐍 Criando ambiente virtual e instalando dependências Python..."
cd ${APP_DIR}
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# --- PASSO 5: Configurar Arquivo .env e Permissões ---
if [ ! -f "${APP_DIR}/.env" ]; then
    echo "📝 Configurando arquivo .env..."
    read -p "Por favor, insira o ID da sua Google Sheet: " sheet_id
    
    cat > ${APP_DIR}/.env << EOF
GOOGLE_SHEETS_KEY=${sheet_id}
SCHEDULE_TIME_1=08:00
SCHEDULE_TIME_2=20:00
RUN_ON_START=true
EOF
    echo -e "${GREEN}✅ Arquivo .env criado.${NC}"
fi

echo "🔒 Ajustando permissões do diretório..."
chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
chmod 755 ${APP_DIR}

# --- PASSO 6: Criar Serviço Systemd ---
SERVICE_FILE="/etc/systemd/system/job-scraper-selenium.service"
echo "⚙️ Criando serviço systemd em ${SERVICE_FILE}..."

cat > ${SERVICE_FILE} << EOF
[Unit]
Description=Health Job Scraper (Selenium Edition)
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/job_search_selenium.py
Restart=always
RestartSec=30
StandardOutput=append:${APP_DIR}/logs/service.log
StandardError=append:${APP_DIR}/logs/service.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable job-scraper-selenium.service

echo -e "${GREEN}✅ Serviço systemd criado e habilitado.${NC}"

# --- Conclusão ---
echo ""
echo "🎉 Instalação concluída!"
echo "O scraper agora usará Selenium para buscas muito mais eficazes."
echo ""
echo "Para iniciar o serviço, execute:"
echo -e "${YELLOW}sudo systemctl start job-scraper-selenium${NC}"
echo ""
echo "Para ver o status e os logs, execute:"
echo -e "${YELLOW}sudo systemctl status job-scraper-selenium${NC}"
echo -e "${YELLOW}tail -f ${APP_DIR}/logs/job_search_selenium.log${NC}"
echo ""
if [ ! -f "${APP_DIR}/credentials.json" ]; then
    echo -e "${RED}❌ AÇÃO NECESSÁRIA: O arquivo 'credentials.json' não foi encontrado. Por favor, copie-o para ${APP_DIR} e ajuste a permissão com 'sudo chown ${APP_USER}:${APP_USER} ${APP_DIR}/credentials.json' antes de iniciar o serviço.${NC}"
fi
