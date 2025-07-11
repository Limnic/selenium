#!/usr/bin/env python3
"""
Script de Busca Automatizada de Vagas com Selenium
Versão robusta que utiliza automação de navegador para extrair dados de sites complexos.
"""

import os
import time
import json
import logging
import gspread
import schedule
from datetime import datetime
from typing import List
from dataclasses import dataclass

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Outras bibliotecas
from oauth2client.service_account import ServiceAccountCredentials
from functools import wraps

# --- Configuração de Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('job_search_selenium.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Configurações Gerais ---
GOOGLE_SHEETS_KEY = os.getenv('GOOGLE_SHEETS_KEY', 'your-sheet-key-here')
CREDENTIALS_FILE = 'credentials.json'

SEARCH_TERMS = [
    "digital health", "telemedicine", "eHealth", "mHealth",
    "health IT", "interoperability health", "FHIR", "HL7",
    "AI healthcare", "health informatics", "digitale Gesundheit", "Telemedizin"
]
LOCATIONS = ["Leipzig", "remote", "Deutschland remote", "Germany remote"]
EXPERIENCE_LEVELS = ["junior", "entry", "graduate", "trainee", "praktikum", "werkstudent"]
EXCLUDE_TERMS = ["project manager", "senior", "lead", "principal", "director", "head of", "developer"]

@dataclass
class JobPosting:
    """Estrutura de dados para uma vaga (simplificada)"""
    title: str
    company: str
    location: str
    languages: List[str]
    link: str
    date_posted: str
    source: str = ""

# --- Gerenciador do WebDriver ---
class WebDriverManager:
    """Gerencia a inicialização e o encerramento do driver do Selenium."""
    def __init__(self):
        self.driver = None

    def start_driver(self):
        """Inicializa o Chrome WebDriver em modo headless."""
        logger.info("Iniciando o WebDriver do Chrome...")
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        try:
            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("WebDriver iniciado com sucesso.")
            return self.driver
        except Exception as e:
            logger.error(f"Falha ao iniciar o WebDriver: {e}")
            logger.error("Verifique se o Google Chrome está instalado no sistema.")
            raise

    def close_driver(self):
        """Encerra o WebDriver se estiver ativo."""
        if self.driver:
            self.driver.quit()
            logger.info("WebDriver encerrado.")

# --- Gerenciador do Google Sheets ---
class GoogleSheetsManager:
    """Gerencia a conexão e operações com Google Sheets."""
    def __init__(self):
        self.worksheet = None
        self._existing_links = set()

    def connect(self):
        logger.info("Conectando ao Google Sheets...")
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEETS_KEY)
        try:
            self.worksheet = sheet.worksheet('Vagas')
        except gspread.WorksheetNotFound:
            self.worksheet = sheet.add_worksheet('Vagas', 1000, 20)
            self._setup_headers()
        self._load_existing_links()
        logger.info("Conectado ao Google Sheets com sucesso.")

    def _setup_headers(self):
        headers = ['Data Cadastro', 'Título', 'Empresa', 'Localização', 'Idiomas', 'Link', 'Data Publicação', 'Fonte']
        self.worksheet.append_row(headers)

    def _load_existing_links(self):
        all_values = self.worksheet.get_all_values()
        if len(all_values) > 1:
            link_column_index = 5  # Coluna F
            self._existing_links = {row[link_column_index] for row in all_values[1:] if len(row) > link_column_index}
        logger.info(f"Carregados {len(self._existing_links)} links existentes.")

    def save_jobs(self, jobs: List[JobPosting]):
        new_jobs = []
        for job in jobs:
            if job.link not in self._existing_links:
                row = [
                    datetime.now().strftime('%Y-%m-%d %H:%M'), job.title, job.company,
                    job.location, ', '.join(job.languages), job.link,
                    job.date_posted, job.source
                ]
                new_jobs.append(row)
                self._existing_links.add(job.link)
        if new_jobs:
            self.worksheet.append_rows(new_jobs, value_input_option='USER_ENTERED')
            logger.info(f"Salvas {len(new_jobs)} novas vagas.")
        else:
            logger.info("Nenhuma vaga nova encontrada para salvar.")

# --- Classe Base do Scraper ---
class JobScraper:
    """Classe base para scrapers que usam Selenium."""
    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(self.driver, 15)

    def is_relevant_job(self, title: str) -> bool:
        title_lower = title.lower()
        if any(exclude in title_lower for exclude in EXCLUDE_TERMS):
            return False
        is_junior = any(level in title_lower for level in EXPERIENCE_LEVELS)
        return is_junior or not any(term in title_lower for term in ["senior", "lead", "principal"])

    def extract_languages(self, text: str) -> List[str]:
        languages = []
        text_lower = text.lower()
        patterns = {'English': ['english', 'englisch'], 'German': ['german', 'deutsch']}
        for lang, terms in patterns.items():
            if any(term in text_lower for term in terms):
                languages.append(lang)
        return languages if languages else ['Not specified']
    
    def search_jobs(self) -> List[JobPosting]:
        raise NotImplementedError("Cada scraper deve implementar seu próprio método de busca.")

# --- Scrapers Específicos (com Selenium) ---

class LinkedInScraper(JobScraper):
    def search_jobs(self) -> List[JobPosting]:
        jobs = []
        logger.info("Buscando no LinkedIn...")
        for term in SEARCH_TERMS[:3]:
            try:
                url = f"https://www.linkedin.com/jobs/search?keywords={term}&location=Germany&f_E=1,2&position=1&pageNum=0"
                self.driver.get(url)
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'ul.jobs-search__results-list')))
                
                # Scroll to load more jobs
                for _ in range(3): # Scroll 3 times
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)

                job_cards = self.driver.find_elements(By.CSS_SELECTOR, 'li.jobs-search-results__list-item')
                for card in job_cards[:20]: # Pega até 20 vagas
                    try:
                        title = card.find_element(By.CSS_SELECTOR, 'h3.base-search-card__title').text
                        if not self.is_relevant_job(title):
                            continue
                        
                        company = card.find_element(By.CSS_SELECTOR, 'h4.base-search-card__subtitle').text
                        location = card.find_element(By.CSS_SELECTOR, 'span.job-search-card__location').text
                        link = card.find_element(By.CSS_SELECTOR, 'a.base-card__full-link').get_attribute('href')
                        
                        jobs.append(JobPosting(
                            title=title, company=company, location=location,
                            languages=self.extract_languages(title), link=link,
                            date_posted=datetime.now().strftime('%Y-%m-%d'), source="LinkedIn"
                        ))
                    except Exception:
                        continue
            except Exception as e:
                logger.error(f"Erro no LinkedIn para o termo '{term}': {e}")
            time.sleep(3)
        return jobs

class GlassdoorScraper(JobScraper):
    def search_jobs(self) -> List[JobPosting]:
        jobs = []
        logger.info("Buscando no Glassdoor...")
        for term in SEARCH_TERMS[:3]:
            try:
                url = f"https://www.glassdoor.de/Job/germany-{term}-jobs-SRCH_IL.0,7_IN96_KO8,{8+len(term)}.htm?fromAge=7"
                self.driver.get(url)

                # Clica no botão de cookies se ele aparecer
                try:
                    self.wait.until(EC.element_to_be_clickable((By.ID, 'onetrust-accept-btn-handler'))).click()
                except Exception:
                    logger.info("Botão de cookies do Glassdoor não encontrado, continuando.")
                
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'ul.JobsList_jobsList__lqjTr')))
                job_cards = self.driver.find_elements(By.CSS_SELECTOR, 'li.JobsList_jobListItem__JBBUV')
                for card in job_cards[:20]:
                    try:
                        title = card.find_element(By.CSS_SELECTOR, 'a[data-test="job-title"]').text
                        if not self.is_relevant_job(title):
                            continue

                        company = card.find_element(By.CSS_SELECTOR, 'div.EmployerProfile_employerInfo__d8uSE > span').text
                        location = card.find_element(By.CSS_SELECTOR, 'div.JobCard_location__rCz3x').text
                        link = card.find_element(By.CSS_SELECTOR, 'a[data-test="job-link"]').get_attribute('href')

                        jobs.append(JobPosting(
                            title=title, company=company, location=location,
                            languages=self.extract_languages(title), link=link,
                            date_posted=datetime.now().strftime('%Y-%m-%d'), source="Glassdoor"
                        ))
                    except Exception:
                        continue
            except Exception as e:
                logger.error(f"Erro no Glassdoor para o termo '{term}': {e}")
            time.sleep(3)
        return jobs

class XINGScraper(JobScraper):
    def search_jobs(self) -> List[JobPosting]:
        jobs = []
        logger.info("Buscando no XING...")
        for term in SEARCH_TERMS[:3]:
            try:
                url = f"https://www.xing.com/jobs/search?keywords={term}&location=Deutschland&radius=100"
                self.driver.get(url)
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-qa="job-listing"]')))
                
                job_listings = self.driver.find_elements(By.CSS_SELECTOR, 'div[data-qa="job-listing"] article')
                for card in job_listings[:20]:
                    try:
                        title_elem = card.find_element(By.CSS_SELECTOR, 'h2 a')
                        title = title_elem.text
                        if not self.is_relevant_job(title):
                            continue
                        
                        link = title_elem.get_attribute('href')
                        company = card.find_element(By.CSS_SELECTOR, 'h3 a').text
                        location = card.find_element(By.CSS_SELECTOR, 'div[data-qa="job-listing-location"]').text

                        jobs.append(JobPosting(
                            title=title, company=company, location=location,
                            languages=self.extract_languages(title), link=link,
                            date_posted=datetime.now().strftime('%Y-%m-%d'), source="XING"
                        ))
                    except Exception:
                        continue
            except Exception as e:
                logger.error(f"Erro no XING para o termo '{term}': {e}")
            time.sleep(3)
        return jobs

# --- Orquestrador ---
class JobSearchOrchestrator:
    """Orquestra a busca de vagas usando Selenium."""
    def __init__(self):
        self.driver_manager = WebDriverManager()
        self.sheets_manager = GoogleSheetsManager()

    def run_search(self):
        start_time = datetime.now()
        logger.info("=" * 50)
        logger.info(f"Iniciando busca de vagas com Selenium: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        driver = None
        try:
            driver = self.driver_manager.start_driver()
            self.sheets_manager.connect()
            
            scrapers = [
                LinkedInScraper(driver),
                GlassdoorScraper(driver),
                XINGScraper(driver)
                # Adicione outros scrapers baseados em Selenium aqui
            ]
            
            all_jobs = []
            for scraper in scrapers:
                try:
                    scraper_name = scraper.__class__.__name__
                    logger.info(f"--- Executando {scraper_name} ---")
                    found_jobs = scraper.search_jobs()
                    logger.info(f"✅ {scraper_name} encontrou {len(found_jobs)} vagas.")
                    all_jobs.extend(found_jobs)
                except Exception as e:
                    logger.error(f"❌ Falha no scraper {scraper.__class__.__name__}: {e}")

            self.sheets_manager.save_jobs(all_jobs)

        except Exception as e:
            logger.critical(f"❌ Erro crítico no orquestrador: {e}")
        finally:
            self.driver_manager.close_driver()
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Busca concluída em {duration:.2f} segundos.")
            logger.info("=" * 50)

def health_check():
    """Verifica as dependências principais."""
    logger.info("🏥 Executando verificação de saúde...")
    ok = True
    if not os.path.exists(CREDENTIALS_FILE):
        logger.error("❌ Arquivo credentials.json não encontrado!")
        ok = False
    try:
        # Testa se o Chrome está acessível
        options = Options()
        options.add_argument("--headless")
        service = ChromeService(ChromeDriverManager().install())
        test_driver = webdriver.Chrome(service=service, options=options)
        test_driver.quit()
        logger.info("✅ WebDriver e Chrome parecem estar configurados corretamente.")
    except Exception as e:
        logger.error(f"❌ Falha na verificação do WebDriver: {e}")
        logger.error("Certifique-se de que o Google Chrome está instalado e o script tem permissão para executá-lo.")
        ok = False
    return ok

def main():
    logger.info("🚀 Iniciando Health Job Scraper (Versão Selenium)")
    
    if not health_check():
        logger.error("❌ Verificação de saúde falhou. Abortando.")
        return

    orchestrator = JobSearchOrchestrator()
    
    if os.getenv('RUN_ON_START', 'true').lower() == 'true':
        orchestrator.run_search()

    schedule_time_1 = os.getenv('SCHEDULE_TIME_1', '08:00')
    schedule_time_2 = os.getenv('SCHEDULE_TIME_2', '20:00')
    
    schedule.every().day.at(schedule_time_1).do(orchestrator.run_search)
    schedule.every().day.at(schedule_time_2).do(orchestrator.run_search)
    
    logger.info(f"⏰ Agendamento configurado para {schedule_time_1} e {schedule_time_2}")
    logger.info("💤 Entrando em modo de espera...")

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
