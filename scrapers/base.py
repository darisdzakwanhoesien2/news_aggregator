from abc import ABC, abstractmethod

class SocialScraper(ABC):

    @abstractmethod
    def fetch_posts(self, identifier: str, limit: int):
        pass

    @abstractmethod
    def fetch_comments(self, post_id: str, limit: int):
        pass
