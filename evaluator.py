from datetime import datetime, date
from typing import List, Optional
from dataclasses import dataclass
from cltre import LTRE, Polarity
import requests
import re
from typing import Set
from urllib.parse import quote

@dataclass
class Article:
    url: str
    score: int
    authors: List[str]
    domain: Optional[str]
    publish_date: Optional[str] # Expected format "YYYY-MM-DD"
    abstract: Optional[str]
    references: List[str]
    doi: bool = False

class ArticleEvaluator:
    def __init__(self):
        self.engine = LTRE("Advanced Article Evaluator")
        self.api_key = "b80a82930c1b47cdb61cb329e3424e22" # may need to update if expires (used for newsapi)
        self.today = date.today()
        self._setup_rules()

    def _get_jaccard_sim(self, str1: str, str2: str) -> float:
        """Calculates the Jaccard Similarity between two strings."""
        def get_tokens(text: str) -> Set[str]:
            # Simple tokenizer: lowercase and remove non-alphanumeric
            return set(re.findall(r'\w+', text.lower()))

        a = get_tokens(str1)
        b = get_tokens(str2)
        
        intersection = len(a.intersection(b))
        union = len(a.union(b))
        
        return intersection / union if union > 0 else 0

    def _get_newspaper_consensus_score(self, article: Article) -> int:
        """Fetch live news and compare similarity using Jaccard Index."""
        news_domains = ["cnn.com", "abcnews.go.com", "nytimes.com", "reuters.com", "apnews.com"]
        
        #don't evaluate if the source has a doi
        if article.doi:
            return 0
        # Check if the source is a recognized news domain
        if not any(domain in (article.domain or "") for domain in news_domains):
            return 0

        if not article.abstract:
            return 0

        # 1. Search for similar articles using NewsAPI
        # Take the first 10-15 words and remove common "stop words"
        raw_text = article.abstract or ""
        # Remove special characters that break queries
        clean_text = re.sub(r'[^\w\s]', '', raw_text)
        words = clean_text.split()
        
        # Only take the first 8-10 unique words for a broad but relevant search
        search_query = " ".join(words[:8]) 

        # 2. URL Encode the query safely
        encoded_query = quote(search_query)
        
        # 3. Use the 'relevancy' sort to ensure the best matches are at the top
        url = (f"https://newsapi.org/v2/everything?"
            f"q={encoded_query}&"
            f"sortBy=relevancy&"
            f"pageSize=5&"
            f"apiKey={self.api_key}")
        print(url)
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if data.get("status") != "ok":
                return 0
            
            comparison_articles = data.get("articles", [])
        except Exception:
            return 0

        # 2. Calculate Similarity
        match_count = 0
        threshold = 0.15 # Jaccard is stricter than SequenceMatcher; 0.15-0.2 is often a solid match
        
        for item in comparison_articles:
            external_abstract = item.get("description") or ""
            sim = self._get_jaccard_sim(article.abstract, external_abstract)
            
            if sim >= threshold:
                match_count += 1

        # 3. Score attribution
        if match_count >= 4: return 20
        if match_count >= 3: return 15
        if match_count >= 2: return 10
        if match_count >= 1: return 5
        return 0

    def _setup_rules(self):
        """Define logical triggers for the engine."""
        # Rule: Social Media Penalty
        def rule_social_media(env, node):
            # This fact will be used to subtract from the score later
            self.engine.assert_fact(("is-unreliable-source", env["?url"]), just="Social Media Domain")
        self.engine.add_rule(("TRUE", ("is-social-media", "?url")), rule_social_media)

        # Rule: Historical bypass
        def rule_historical(env, node):
            self.engine.assert_fact(("ignore-recency", env["?url"]), just="Historical Content")
        self.engine.add_rule(("TRUE", ("is-historical", "?url")), rule_historical)

    def _is_historical(self, article: Article) -> bool:
        """Heuristic to check if the article is about history."""
        keywords = ["battle", "war of", "century", "ancient", "history", "civilization"]
        text = f"{article.abstract} {article.url}".lower()
        return any(k in text for k in keywords)

    def evaluate(self, article: Article) -> float:
        url = article.url

        # 1. Assert Domain Facts
        social_media = ["facebook.com", "x.com", "twitter.com", "instagram.com", "reddit.com", "tiktok.com"]
        if article.domain in social_media:
            self.engine.assert_fact(("is-social-media", url))

        # 2. Check for Historical Context
        if self._is_historical(article):
            self.engine.assert_fact(("is-historical", url))

        # 3. Handle DOI
        if article.doi:
            self.engine.assert_fact(("has-doi", url))

        self.engine.run_rules()
        return self._calculate_score(url, article)

    def _calculate_score(self, url: str, article: Article):
        score = 0.0
        
        # --- 1. Domain Weighting (Base Score: 30 pts max) ---
        domain_weights = {".gov": 30, ".edu": 30, ".org": 20, ".com": 15}
        domain_score = 0
        if article.domain:
            for ext, weight in domain_weights.items():
                if article.domain.endswith(ext):
                    domain_score = weight
                    break
            if domain_score == 0:
                domain_score = 5
        score += domain_score

        # --- 2. Author Check (10 pts max) ---
        # Checks if the authors list is not empty and has valid strings
        if article.authors and len(article.authors) > 0:
            score += 10

        # --- 3. Reference Scaling (20 pts max) ---
        ref_count = len(article.references)
        if ref_count >= 10: score += 20
        elif ref_count >= 5: score += 10
        elif ref_count >= 1: score += 5

        # --- 4. Recency % Score (Max 20) ---
        # Adjusted logic: check if fact exists before accessing datum
        hist_fact = self.engine.get_dbclass(("ignore-recency", url))
        if hist_fact and self.engine.tms.is_true(hist_fact.datum):
            score += 20
        elif article.publish_date:
            try:
                pub_dt = datetime.strptime(article.publish_date, "%Y-%m-%d").date()
                days_old = (self.today - pub_dt).days
                recency_ratio = max(0, (5840 - days_old) / 5840)
                score += (recency_ratio * 20)
            except (ValueError, TypeError):
                pass

        # --- 5. DOI/Peer Review or Live Newspaper Consensus (20 pts max) ---
        if article.doi:
            score += 20
        else:
            score += self._get_newspaper_consensus_score(article)

        # --- 6. Penalties ---
        bad_fact = self.engine.get_dbclass(("is-unreliable-source", url))
        if bad_fact and self.engine.tms.is_true(bad_fact.datum):
            score -= 50

        article.score = int(min(max(score, 0), 100))