from dataclasses import dataclass
from typing import List, Optional
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from dateutil import parser
from urllib.parse import urlparse
import re
from html import unescape
import sqlite3
from evaluator import ArticleEvaluator
# =========================================================
# get the set of sources from the LLM
# =========================================================

#store the related atributes to then store in the database
@dataclass
class Article:
    """container for all the properties of an article, used to then store the article in the database"""
    url: str
    score: int
    authors: List[str]
    domain: Optional[str]
    publish_date: Optional[str]
    abstract: Optional[str]
    references: List[str]
    doi: bool = False
    
def create_database():
    """create the table if it has not been made already"""
    #get the soruces database
    conn = sqlite3.connect("sources.db")

    #make a cursor to call the database
    cursor = conn.cursor()

    #create the table we need
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sources (
                   url TEXT PRIMARY KEY,
                   score INTEGER,
                   authors TEXT,
                   domain TEXT,
                   publish_date DATE,
                   abstract TEXT,
                   has_doi BOOLEAN
                   )'''
                   )
    conn.commit()
    conn.close()

def array_to_string(List: List[str]) -> str:
    """converts a array of strings into one string as a comma list"""
    result = List[0]
    for i in range(1, len(List)):
        result = result + ", " + List[i]
    return result

def add_to_database(article: Article):
    """opens the database file and adds the article into the sources table within"""
    #get the soruces database
    conn = sqlite3.connect("sources.db")

    #make a cursor to call the database
    cursor = conn.cursor()

    #add the article if it doesn't exist
    try:
        cursor.execute(f'''
            INSERT INTO sources (url, score, authors, domain, publish_date, has_doi, abstract)
            VALUES("{article.url}", "{article.score}", "{array_to_string(article.authors)}", "{article.domain}", "{article.publish_date}", "{article.doi}", "{article.abstract}")'''
        )
        conn.commit()
        conn.close()
    except(sqlite3.IntegrityError):
        conn.close() #the url has been added already so we can just close the connection

def scrape_DOI(data, domain, url) -> Article:
    """helper function for scrape_article, handles any doi urls"""
     # --- Author ---
    # Extract and format names in one go
    authors: List[str] = [
    name for a in data.get("author", [])
    if (name := f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get('name', '').strip())
    ]
    # --- Publish Date ---
    publish_date = None
    if "issued" in data:
        parts = data["issued"].get("date-parts", [])
        if parts and parts[0]: 
            y, m, d = (parts[0] + [1, 1, 1])[:3] # get only the date
            publish_date = f"{y:04d}-{m:02d}-{d:02d}"

    # --- References ---
    references = []
    if "reference" in data:
        for ref in data["reference"]: # get the refernces
            if "DOI" in ref: #how to structure the reference
                references.append(ref["DOI"])
            elif "unstructured" in ref:
                references.append(ref["unstructured"])

    # --- Abstract ---
    abstract = None
    raw_abstract = data.get("abstract")

    if raw_abstract:
        # CrossRef abstracts are often HTML/XML like:
        # "<jats:p>This is the abstract...</jats:p>"
        
        # Remove XML/HTML tags
        abstract = unescape(re.sub(r"<.*?>", "", raw_abstract)).strip()

    return Article(
        url=url,
        score=0,
        authors=authors,
        domain=domain,
        publish_date=publish_date,
        references=references,
        doi=True,
        abstract = abstract
    )

def standardize_date(str: str) -> str | None:
    """make it so all dates are formated the same for ease of navigation"""
    if not str:
        return None
    # Find the first occurrence of a date-like pattern
    match = re.search(r"\d{1,2}\s+\w+\s+\d{4}", str)
    if not match:
        return None
    date_text = match.group(0)
    try: # Convert to the format the database uses
        dt = parser.parse(date_text)
        return dt.date().isoformat()  # YYYY-MM-DD
    except (ValueError, TypeError):
        return None


def scrape_article(url: str) -> Article:
    """scrape an article for relevent information for evaluating creadibility and save summery/abstract"""

    #make the database if it does not exist
    create_database()

    # --- DOI CASE ---
    #if doi, parse as a JSON file
    if("/doi/" in url or "/doi.org/" in url):
        #get the doi number
        match = re.search(r'10\.\d{4,9}/\S+', url)
        doi = match.group(0) if match else None
        #convert ot crossref to get article
        url_doi = "https://api.crossref.org/works/" + doi
        try:
            response = requests.get(url_doi, timeout=10)
            response.raise_for_status()

            #scrape as a JSON
            article = scrape_DOI(response.json()["message"], urlparse(url).hostname, url)

            # --- evaluate the article ---
            ArticleEvaluator().evaluate(article)
            return article

        except requests.RequestException: #doi may be custom
            has_doi=True

    # --- Create Scraper ---
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
    # if parser fails to create, then it's possible that the site is dynamic, so use seleium to load
    except requests.RequestException:
        options = Options()
        options.add_argument("--headless=new")
        driver = webdriver.Chrome(options=options)

        try:
            driver.get(url)

            #wait for JS to render
            driver.implicitly_wait(5)

            html = driver.page_source
            return BeautifulSoup(html, "html.parser")

        finally:
            driver.quit()

    #sometimes DOI is in the webpage and not the url, check before tring non-doi referecning
    doi_tag = soup.select_one('td.tablecell a[href*="doi.org"]')
    doi = doi_tag['href'] if doi_tag else None
    has_doi = False
    if doi:
        has_doi = True
    # --- Author extraction ---
    # 1. Try metadata (most reliable for articles)
    authors = [
        m["content"]
        for m in soup.find_all("meta", attrs={"name": "citation_author"})
    ]

    # 2. If empty, try known structural selectors
    if not authors:
        authors = [
            a.get_text(strip=True)
            for a in soup.find_all("span", class_="author-name")

        ]

    # 3. Fallback to heuristic
    if not authors:
        for tag in soup.find_all(True):
            if tag.get("class") and any("author" in c.lower() for c in tag.get("class")):
                text = tag.get_text(strip=True)
                if text:
                    authors.append(text)

    # 4. Clean
    if("By" in authors[0]):
        authors.pop(0)
    authors = list(dict.fromkeys(authors))

    
    # --- Date extraction ---
    publish_date = None

    # First, try to find a <time> tag
    date_tag = soup.find("time")
    if date_tag and date_tag.get("datetime"):
        publish_date = standardize_date(date_tag["datetime"])
    elif date_tag:
        publish_date = standardize_date(date_tag.get_text(strip=True))
    else:
        # Fallback: check for <div class="dateline">
        date_tag = soup.find("div", class_="dateline")
        if date_tag:
            publish_date = standardize_date(date_tag.get_text(strip=True))
    # --- References extraction ---
    references = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "reference" in a.get_text().lower():
            references.append(href)
    
    # --- create article ---
    article = Article(
        url=url,
        score=0,
        authors=authors,
        domain=urlparse(url).hostname,
        publish_date=publish_date,
        references=references,
        abstract="",
        doi=has_doi
    )
    # --- evaluate the article ---
    ArticleEvaluator().evaluate(article)
    return article

add_to_database(scrape_article("https://dl.acm.org/doi/10.1145/3571730"))