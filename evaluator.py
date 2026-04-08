from datetime import datetime, date
from typing import List, Optional
from dataclasses import dataclass
from cltre import LTRE, Polarity

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
        self.today = date.today()
        self._setup_rules()

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
        elif ref_count >= 5: score += 15
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

        # --- 5. DOI/Peer Review (20 pts max) ---
        if article.doi:
            score += 20

        # --- 6. Penalties ---
        bad_fact = self.engine.get_dbclass(("is-unreliable-source", url))
        if bad_fact and self.engine.tms.is_true(bad_fact.datum):
            score -= 50

        article.score = int(min(max(score, 0), 100))