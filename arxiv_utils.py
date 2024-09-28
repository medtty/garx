import requests
import time
import os
from xml.etree import ElementTree
import configparser
import google.generativeai as genai
import traceback
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import subprocess

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load API keys and settings
config = configparser.ConfigParser()
with open('key.ini') as config_file:
    config.read_file(config_file)

def fetch_arxiv_papers(query, max_results=5, retries=3):
    base_url = "http://export.arxiv.org/api/query?"
    search_query = f"search_query=all:{query}&start=0&max_results={max_results}"

    for attempt in range(retries):
        try:
            response = requests.get(base_url + search_query)
            response.raise_for_status()
            return parse_arxiv_response(response.content)
        except requests.exceptions.HTTPError as e:
            if response.status_code == 502:
                logging.warning("Received 502, retrying...")
                time.sleep(2)
            else:
                logging.error(f"Error fetching papers: {e}")
                break
    return None

def parse_arxiv_response(content):
    root = ElementTree.fromstring(content)
    papers = []
    for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
        paper_id = entry.find("{http://www.w3.org/2005/Atom}id").text.split("/")[-1]
        published_date = entry.find("{http://www.w3.org/2005/Atom}published").text.split("T")[0]
        authors = [author.find("{http://www.w3.org/2005/Atom}name").text for author in entry.findall("{http://www.w3.org/2005/Atom}author")]
        
        paper = {
            "id": paper_id,
            "title": entry.find("{http://www.w3.org/2005/Atom}title").text,
            "summary": entry.find("{http://www.w3.org/2005/Atom}summary").text,
            "pdf_url": next(link.get('href') for link in entry.findall("{http://www.w3.org/2005/Atom}link") if link.get('title') == 'pdf'),
            "published_date": published_date,
            "authors": authors,
        }
        papers.append(paper)
    return papers

def download_paper(pdf_url, paper_id):
    response = requests.get(pdf_url)
    if response.status_code == 200:
        filename = f"{paper_id}.pdf"
        with open(filename, 'wb') as f:
            f.write(response.content)
        return filename
    else:
        return None

def open_pdf(filename):
    if os.name == 'nt':  # For Windows
        os.startfile(filename)
    elif os.name == 'posix':  # For macOS and Linux
        opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
        subprocess.call([opener, filename])

def api_request(api_key, api_base, model, role, content, max_tokens=500):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": role},
            {"role": "user", "content": content}
        ],
        "max_tokens": max_tokens
    }
    
    try:
        response = requests.post(f"{api_base}/chat/completions", headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json().get('choices', [{}])[0].get('message', {}).get('content', '')
    except requests.exceptions.RequestException as e:
        logging.error(f"Error in API request: {str(e)}")
        return f"Error in API request: {str(e)}"

def summarize_with_groq(text):
    api_key = config['Groq']['API_KEY']
    api_base = config['Groq']['API_BASE']
    model = config['Groq']['GROQ_MODEL']
    return api_request(api_key, api_base, model, 
                       "You are a helpful assistant that summarizes scientific papers.", 
                       f"Please summarize the following scientific paper:\n\n{text}")

def polish_with_groq(text):
    api_key = config['Groq']['API_KEY']
    api_base = config['Groq']['API_BASE']
    model = config['Groq']['GROQ_MODEL']
    return api_request(api_key, api_base, model, 
                       "You are a helpful assistant that polishes and improves text.", 
                       f"Please polish and improve the following text:\n\n{text}")

def talk_to_paper_with_groq(paper_content, question):
    api_key = config['Groq']['API_KEY']
    api_base = config['Groq']['API_BASE']
    model = config['Groq']['GROQ_MODEL']  # Adjust as necessary for the chat model

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a knowledgeable assistant that answers questions based on scientific papers."},
            {"role": "user", "content": f"Based on the following paper content, answer this question:\n\nQuestion: {question}\n\nPaper content: {paper_content}"}
        ],
        "max_tokens": 500
    }

    try:
        logging.info("Sending request to Groq API for paper chat")
        response = requests.post(f"{api_base}/chat/completions", headers=headers, json=data, timeout=30)
        response.raise_for_status()
        chat_response = response.json()['choices'][0]['message']['content']
        logging.info("Successfully received response from Groq API for paper chat")
        return chat_response
    except requests.exceptions.RequestException as e:
        logging.error(f"Error in talking to paper with Groq: {str(e)}")
        return f"Error in talking to paper with Groq: {str(e)}"

def run_with_timeout(func, args, timeout):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            logging.error(f"Operation timed out for function: {func.__name__}")
            return "Error: Operation timed out"

def translate_with_groq(text, target_language="en"):
    api_key = config['Groq']['API_KEY']
    api_base = config['Groq']['API_BASE']
    model = config['Groq']['GROQ_MODEL']  # Adjust as necessary for the translation model

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a translation assistant."},
            {"role": "user", "content": f"Translate the following text to {target_language}:\n\n{text}"}
        ],
        "max_tokens": 500
    }

    try:
        logging.info("Sending request to Groq API for translation")
        response = requests.post(f"{api_base}/chat/completions", headers=headers, json=data, timeout=30)
        response.raise_for_status()
        translated_text = response.json()['choices'][0]['message']['content']
        logging.info("Successfully received translation from Groq API")
        return translated_text
    except requests.exceptions.RequestException as e:
        logging.error(f"Error in translation with Groq: {str(e)}")
        return f"Error in translation with Groq: {str(e)}"

def summarize_paper(text):
    return summarize_with_groq(text)
