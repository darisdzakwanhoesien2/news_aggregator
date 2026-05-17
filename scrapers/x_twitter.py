import snscrape.modules.twitter as sntwitter

class XTwitterScraper:

    def fetch_posts(self, query: str, limit: int = 20):
        posts = []
        for i, tweet in enumerate(sntwitter.TwitterSearchScraper(query).get_items()):
            if i >= limit:
                break

            posts.append({
                "platform": "x",
                "post_id": tweet.id,
                "text": tweet.content,
                "author": tweet.user.username,
                "created_at": tweet.date.isoformat(),
                "url": tweet.url,
                "reply_count": tweet.replyCount,
                "like_count": tweet.likeCount
            })

        return posts

    def fetch_comments(self, post_id: str, limit: int = 50):
        # X does not expose replies reliably without conversation ID
        return []
