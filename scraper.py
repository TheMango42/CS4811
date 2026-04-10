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
from newspaper import Article as NewsArticle # Avoid collision with your dataclass
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
        # Use ? placeholders to safely inject text (like abstracts with quotes)
        query = '''
            INSERT INTO sources (url, score, authors, domain, publish_date, has_doi, abstract)
            VALUES (?, ?, ?, ?, ?, ?, ?)'''
        
        cursor.execute(query, (
            article.url, 
            article.score, 
            array_to_string(article.authors) if article.authors else "", 
            article.domain, 
            article.publish_date, 
            article.doi, 
            article.abstract
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # URL already exists
    finally:
        conn.close()

def source_in_db(url):
    """
    Checks if a URL already exists in the sources table.
    """
    # Connect to the database
    conn = sqlite3.connect("sources.db")
    cursor = conn.cursor()

    # We use 'EXISTS' or 'SELECT 1' for performance since we don't need the actual data
    query = "SELECT 1 FROM sources WHERE url = ? LIMIT 1"
    
    cursor.execute(query, (url,))
    result = cursor.fetchone()

    # Close connection
    conn.close()

    # If result is not None, the URL exists
    return result is not None

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
    domain = urlparse(url).hostname
    #make the database if it does not exist
    create_database()

    # Define news outlets to trigger Newspaper4k
    news_domains = [
        "cnn.com", "bbc.co.uk", "nytimes.com", "reuters.com", "apnews.com", 
        "abcnews.go.com", "theguardian.com", "aljazeera.com", "forbes.com", "wsj.com"
    ]
    is_news_outlet = any(nd in domain for nd in news_domains)

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

    # --- NEWS OUTLET CASE ---
    if is_news_outlet:
        try:
            #use Newspaper4k to generate summery of article
            n_article = NewsArticle(url)
            n_article.download()
            n_article.parse()
            n_article.nlp() # Required to populate n_article.summary
            
            #create article
            article = Article(
                url=url,
                score=0,
                authors=n_article.authors,
                domain=domain,
                publish_date=n_article.publish_date.strftime("%Y-%m-%d") if n_article.publish_date else None,
                references=[], # Newspaper4k doesn't extract links well; handled in fallback
                abstract=n_article.summary,
                doi=False
            )
            
            # Use BS4 logic just to grab references since n4k lacks them
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            article.references = [a["href"] for a in soup.find_all("a", href=True) if "reference" in a.get_text().lower()]
            
            # --- evaluate the article ---
            ArticleEvaluator().evaluate(article)
            return article
        except Exception as e:
            print(f"Newspaper4k failed, falling back to manual scrape: {e}")

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
        domain=domain,
        publish_date=publish_date,
        references=references,
        abstract="",
        doi=has_doi
    )
    # --- evaluate the article ---
    ArticleEvaluator().evaluate(article)
    return article

add_to_database(scrape_article("https://www.cnn.com/2026/04/10/politics/kamala-harris-2028-presidential-election"))