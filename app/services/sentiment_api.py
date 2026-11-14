"""
Simple API client for external sentiment analysis service.
This is a lightweight client that only makes HTTP requests.
"""
import os
import requests
from typing import Dict, List, Any, Optional


class SentimentAPIClient:
    """Simple client for calling external sentiment analysis API."""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 10):
        """
        Initialize the sentiment API client.

        Args:
            base_url: The base URL of the sentiment service
            timeout: Request timeout in seconds (reduced from 30 to 10)
        """
        # Prefer SENTIMENT_API_URL, fall back to MODAL_ML_BASE_URL for compatibility
        env_base = os.getenv('SENTIMENT_API_URL') or os.getenv('MODAL_ML_BASE_URL') or ''
        self.base_url = (base_url or env_base).strip()
        self.external_enabled = os.getenv('ENABLE_EXTERNAL_AI', '').lower() == 'true'
        # Allow overriding timeout via env
        env_timeout = os.getenv('SENTIMENT_API_TIMEOUT')
        self.timeout = int(env_timeout) if env_timeout else timeout
        # Controls to compact summarize payload
        self.max_summary_comments = int(os.getenv('MAX_SUMMARY_COMMENTS', '300'))
        self.max_comment_length = int(os.getenv('MAX_SUMMARY_COMMENT_CHARS', '300'))

        # Optional API key support
        self.api_key = os.getenv('MODAL_ML_API_KEY') or os.getenv('SENTIMENT_API_KEY')
        self.headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if self.api_key:
            # Support either Bearer or X-API-Key styles
            self.headers['Authorization'] = f'Bearer {self.api_key}'
            self.headers['X-API-Key'] = self.api_key

        if not self.base_url:
            # If no URL configured, use a mock response
            self.mock_mode = True
        else:
            self.mock_mode = False
            self.base_url = self.base_url.rstrip('/')

    def make_request(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generic POST request to the external ML service.
        Returns parsed JSON or a dict with success=False and an error message.
        """
        if not self.external_enabled:
            return {'success': False, 'error': 'External AI is disabled.'}
        if self.mock_mode or not self.base_url:
            return {
                'success': False,
                'error': 'Sentiment API base URL is not configured.'
            }
        try:
            response = requests.post(
                f"{self.base_url}{endpoint}",
                json=payload,
                timeout=self.timeout,
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            return data
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        Analyze sentiment of a single text.

        Args:
            text: The text to analyze

        Returns:
            Dictionary with sentiment analysis results
        """
        # In-process mock data never leaves the machine. A configured URL is not
        # enough to turn on a paid request; that still requires ENABLE_EXTERNAL_AI.
        if self.mock_mode:
            return self._mock_analyze_text(text)
        if not self.external_enabled:
            return {'success': False, 'error': 'External AI is disabled.'}

        try:
            response = requests.post(
                f"{self.base_url}/analyze-text",
                json={"text": text},
                timeout=self.timeout,
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()

            # Extract result from response (support multiple shapes)
            result = data.get('result') or data
            return {
                'sentiment': result.get('predicted_sentiment', result.get('sentiment', 'neutral')),
                'confidence': result.get('confidence', 0.5),
                'models_used': result.get('models_used') or data.get('models_used'),
                'success': True,
            }
        except Exception as e:
            # Return fallback response on error
            return {
                'sentiment': 'neutral',
                'confidence': 0.0,
                'success': False,
                'error': str(e),
            }

    def analyze_batch(self, texts: List[str]) -> Dict[str, Any]:
        """
        Analyze sentiment of multiple texts.

        Args:
            texts: List of texts to analyze

        Returns:
            Dictionary with batch analysis results
        """
        if not texts:
            return {
                'results': [],
                'total_analyzed': 0,
                'success': True,
                'statistics': {
                    'sentiment_distribution': {},
                    'sentiment_percentages': {},
                    'average_confidence': 0.0,
                },
            }
        if self.mock_mode:
            return self._mock_analyze_batch(texts)
        if not self.external_enabled:
            return {'success': False, 'error': 'External AI is disabled.'}

        # Since batch endpoint has issues, use individual analysis as fallback
        # First try the batch endpoint
        try:
            response = requests.post(
                f"{self.base_url}/analyze-batch",
                json={"texts": texts},
                timeout=self.timeout,
                headers=self.headers,
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if we got valid results
                if data.get('success') and data.get('results'):
                    # Normalize results
                    raw_results = data.get('results') or []
                    results = []
                    for item in raw_results:
                        results.append({
                            'text': item.get('text', ''),
                            'predicted_sentiment': item.get('predicted_sentiment') or item.get('sentiment', 'neutral'),
                            'sentiment': item.get('predicted_sentiment') or item.get('sentiment', 'neutral'),
                            'confidence': item.get('confidence', 0.5),
                            'sentiment_scores': item.get('sentiment_scores', {}),
                            'comment_id': item.get('comment_id'),
                        })

                    total = len(results)
                    stats = data.get('statistics') or {}
                    dist = stats.get('sentiment_distribution') or {}
                    if not dist and results:
                        dist = {'positive': 0, 'neutral': 0, 'negative': 0}
                        for r in results:
                            s = r.get('predicted_sentiment') or r.get('sentiment') or 'neutral'
                            if s not in dist:
                                s = 'neutral'
                            dist[s] += 1
                    avg_conf = stats.get('average_confidence')
                    if avg_conf is None:
                        avg_conf = sum(r.get('confidence', 0.0) for r in results) / total if total else 0.0
                    pct = stats.get('sentiment_percentages') or {
                        k: (v / total * 100.0 if total else 0.0) for k, v in dist.items()
                    }

                    return {
                        'results': results,
                        'total_analyzed': total,
                        'statistics': {
                            'sentiment_distribution': dist,
                            'sentiment_percentages': pct,
                            'average_confidence': avg_conf,
                        },
                        'success': True,
                    }
        except Exception as e:
            print(f"Batch endpoint failed: {e}, falling back to individual analysis")
        
        # Fallback: analyze texts in smaller batches for better performance
        results = []
        distribution = {'positive': 0, 'neutral': 0, 'negative': 0}
        confidence_sum = 0.0
        
        # Process in smaller chunks with fewer workers for better stability
        chunk_size = 5  # Reduced from 10
        max_workers = 3  # Reduced from 5
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time
        
        def analyze_chunk(chunk_texts):
            chunk_results = []
            for text in chunk_texts:
                try:
                    # Add small delay to avoid overwhelming the API
                    time.sleep(0.1)
                    result = self.analyze_text(text)
                    if result.get('success', False):
                        sentiment = result.get('sentiment', 'neutral')
                        confidence = result.get('confidence', 0.5)
                        chunk_results.append({
                            'text': text[:100],
                            'predicted_sentiment': sentiment,
                            'sentiment': sentiment,
                            'confidence': confidence,
                            'sentiment_scores': {
                                'positive': 1.0 if sentiment == 'positive' else 0.0,
                                'neutral': 1.0 if sentiment == 'neutral' else 0.0,
                                'negative': 1.0 if sentiment == 'negative' else 0.0,
                            }
                        })
                    else:
                        chunk_results.append({
                            'text': text[:100],
                            'predicted_sentiment': 'neutral',
                            'sentiment': 'neutral',
                            'confidence': 0.5,
                            'sentiment_scores': {'positive': 0.0, 'neutral': 1.0, 'negative': 0.0}
                        })
                except Exception as e:
                    print(f"Individual analysis failed: {e}")
                    chunk_results.append({
                        'text': text[:100],
                        'predicted_sentiment': 'neutral',
                        'sentiment': 'neutral',
                        'confidence': 0.5,
                        'sentiment_scores': {'positive': 0.0, 'neutral': 1.0, 'negative': 0.0}
                    })
            return chunk_results
        
        # Split texts into chunks and process concurrently
        chunks = [texts[i:i+chunk_size] for i in range(0, len(texts), chunk_size)]
        
        # If we have very few texts, just process them sequentially
        if len(texts) <= 10:
            for text in texts:
                try:
                    result = self.analyze_text(text)
                    if result.get('success', False):
                        sentiment = result.get('sentiment', 'neutral')
                        confidence = result.get('confidence', 0.5)
                        results.append({
                            'text': text[:100],
                            'predicted_sentiment': sentiment,
                            'sentiment': sentiment,
                            'confidence': confidence,
                            'sentiment_scores': {
                                'positive': 1.0 if sentiment == 'positive' else 0.0,
                                'neutral': 1.0 if sentiment == 'neutral' else 0.0,
                                'negative': 1.0 if sentiment == 'negative' else 0.0,
                            }
                        })
                        distribution[sentiment] += 1
                        confidence_sum += confidence
                    else:
                        results.append({
                            'text': text[:100],
                            'predicted_sentiment': 'neutral',
                            'sentiment': 'neutral',
                            'confidence': 0.5,
                            'sentiment_scores': {'positive': 0.0, 'neutral': 1.0, 'negative': 0.0}
                        })
                        distribution['neutral'] += 1
                        confidence_sum += 0.5
                except Exception as e:
                    print(f"Sequential analysis failed: {e}")
                    results.append({
                        'text': text[:100],
                        'predicted_sentiment': 'neutral',
                        'sentiment': 'neutral',
                        'confidence': 0.5,
                        'sentiment_scores': {'positive': 0.0, 'neutral': 1.0, 'negative': 0.0}
                    })
                    distribution['neutral'] += 1
                    confidence_sum += 0.5
        else:
            # Use concurrent processing for larger batches
            import concurrent.futures
            
            # Track completed and failed futures
            completed_count = 0
            failed_count = 0
            total_futures = len(chunks)
            
            try:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(analyze_chunk, chunk) for chunk in chunks]
                    
                    # Process completed futures with timeout
                    try:
                        for future in as_completed(futures, timeout=30):
                            try:
                                chunk_results = future.result(timeout=5)
                                completed_count += 1
                                for result in chunk_results:
                                    results.append(result)
                                    sentiment = result['predicted_sentiment']
                                    distribution[sentiment] += 1
                                    confidence_sum += result['confidence']
                            except Exception as e:
                                failed_count += 1
                                print(f"Chunk processing failed: {e}")
                                # Add neutral results for failed chunk
                                for _ in range(chunk_size):
                                    results.append({
                                        'text': 'Error processing',
                                        'predicted_sentiment': 'neutral',
                                        'sentiment': 'neutral',
                                        'confidence': 0.5,
                                        'sentiment_scores': {'positive': 0.0, 'neutral': 1.0, 'negative': 0.0}
                                    })
                                    distribution['neutral'] += 1
                                    confidence_sum += 0.5
                    
                    except concurrent.futures.TimeoutError as timeout_err:
                        # Handle timeout gracefully
                        unfinished_count = total_futures - completed_count - failed_count
                        print(f"Sentiment analysis timeout: {unfinished_count} chunks unfinished out of {total_futures}")
                        
                        # Cancel remaining futures
                        for future in futures:
                            if not future.done():
                                future.cancel()
                        
                        # Add neutral results for unfinished chunks
                        for _ in range(unfinished_count * chunk_size):
                            results.append({
                                'text': 'Processing timeout',
                                'predicted_sentiment': 'neutral',
                                'sentiment': 'neutral',
                                'confidence': 0.5,
                                'sentiment_scores': {'positive': 0.0, 'neutral': 1.0, 'negative': 0.0}
                            })
                            distribution['neutral'] += 1
                            confidence_sum += 0.5
                        
                        # If we have at least some results, continue
                        if completed_count > 0:
                            print(f"Continuing with {completed_count}/{total_futures} completed chunks")
                        else:
                            # If no chunks completed, raise a more user-friendly error
                            raise Exception("Analysis is taking longer than expected. The service might be experiencing high load. Please try again with fewer comments or wait a moment before retrying.")
                    
            except Exception as executor_error:
                if "longer than expected" in str(executor_error):
                    raise  # Re-raise our custom error
                else:
                    # Generic executor error
                    print(f"Executor error: {executor_error}")
                    raise Exception(f"Analysis service error: Unable to process comments at this time. Please try again.")
        
        total = len(results)
        pct = {k: (v / total * 100.0 if total else 0.0) for k, v in distribution.items()}
        avg_conf = confidence_sum / total if total else 0.0
        
        return {
            'results': results,
            'total_analyzed': total,
            'statistics': {
                'sentiment_distribution': distribution,
                'sentiment_percentages': pct,
                'average_confidence': avg_conf,
            },
            'success': True,
        }

    def _mock_analyze_text(self, text: str) -> Dict[str, Any]:
        """Mock response for single text analysis."""
        # Simple mock logic based on keywords
        text_lower = text.lower()
        if any(word in text_lower for word in ['good', 'great', 'excellent', 'love', 'amazing']):
            sentiment = 'positive'
            confidence = 0.85
        elif any(word in text_lower for word in ['bad', 'terrible', 'hate', 'awful', 'worst']):
            sentiment = 'negative'
            confidence = 0.85
        else:
            sentiment = 'neutral'
            confidence = 0.70

        return {
            'sentiment': sentiment,
            'confidence': confidence,
            'success': True,
            'mock': True,
        }

    def _mock_analyze_batch(self, texts: List[str]) -> Dict[str, Any]:
        """Mock response for batch analysis."""
        results = []
        distribution = {'positive': 0, 'neutral': 0, 'negative': 0}

        for text in texts:
            result = self._mock_analyze_text(text)
            results.append({
                'text': text[:100],  # Truncate for display
                'predicted_sentiment': result['sentiment'],
                'sentiment': result['sentiment'],
                'confidence': result['confidence'],
            })
            distribution[result['sentiment']] += 1
        total = len(results)
        pct = {k: (v / total * 100.0 if total else 0.0) for k, v in distribution.items()}
        avg_conf = sum(r.get('confidence', 0.0) for r in results) / total if total else 0.0

        return {
            'results': results,
            'total_analyzed': total,
            'statistics': {
                'sentiment_distribution': distribution,
                'sentiment_percentages': pct,
                'average_confidence': avg_conf,
            },
            'success': True,
            'mock': True,
        }

    def summarize(self, comments: List[Dict[str, Any]], sentiment: Optional[Dict[str, Any]] = None, method: str = "auto", video_title: Optional[str] = None) -> Dict[str, Any]:
        """Request comment summary from the external ML service.
        This compacts the payload to avoid timeouts or 400s due to oversized/malformed inputs.
        """
        # Prepare compact list of comment texts
        def _to_text_list(raw: List[Any]) -> List[str]:
            texts: List[str] = []
            for item in raw or []:
                if isinstance(item, dict):
                    t = item.get('text')
                else:
                    t = str(item)
                if not t:
                    continue
                t = t.strip()
                if not t:
                    continue
                # Truncate excessively long comments
                texts.append(t[: self.max_comment_length])
                if len(texts) >= self.max_summary_comments:
                    break
            return texts

        # Prepare compact sentiment statistics for summary guidance
        def _compact_sentiment(s: Optional[Dict[str, Any]]) -> Dict[str, Any]:
            if not isinstance(s, dict):
                return {}
            stats = s.get('statistics') or {}
            dist = s.get('sentiment_counts') or s.get('distribution') or stats.get('sentiment_distribution') or {}
            avg_conf = s.get('average_confidence') or stats.get('average_confidence') or 0.0
            total = s.get('total_analyzed') or stats.get('total_analyzed') or 0
            # Only pass minimal keys
            return {
                'sentiment_distribution': {
                    'positive': dist.get('positive', 0),
                    'neutral': dist.get('neutral', 0),
                    'negative': dist.get('negative', 0),
                },
                'average_confidence': float(avg_conf),
                'total_analyzed': int(total),
            }

        compact_comments = _to_text_list(comments)
        compact_sentiment = _compact_sentiment(sentiment)
        

        # Use ML service's OpenAI summarization endpoint exclusively
        try:
            # Prepare comments in the format expected by the service
            comment_dicts = []
            for c in comments:
                if isinstance(c, dict):
                    comment_dicts.append(c)
                else:
                    comment_dicts.append({'text': str(c)})

            # Call the summarization endpoint
            summary_response = self.make_request('/summarize', {
                'comments': comment_dicts[:300],  # Limit to 300 comments for performance
                'sentiment': compact_sentiment,
                'video_title': video_title,  # Pass video title for filtering redundant words
                'method': 'auto'  # Let the service choose OpenAI (or fail)
            })

            if summary_response.get('success') and summary_response.get('summary'):
                summary_result = summary_response['summary']
                return {
                    'summary': {
                        'summary': summary_result.get('summary', ''),
                        'method': f"service_{summary_result.get('method', 'unknown')}",
                        'comments_analyzed': summary_result.get('comments_analyzed', compact_sentiment.get('total_analyzed', 0)),
                        'confidence': compact_sentiment.get('average_confidence', 0),
                        'key_themes': summary_result.get('key_themes', []),
                        'engagement_metrics': summary_result.get('engagement_metrics', {})
                    }
                }
            else:
                # Return error without legacy fallback
                return {
                    'error': summary_response.get('error', 'Summarization service returned an unsuccessful response')
                }
        except Exception as e:
            # Return error without legacy fallback
            return {
                'error': str(e)
            }


# Singleton instance
_client = None

def get_sentiment_client() -> SentimentAPIClient:
    """Get or create the sentiment API client."""
    global _client
    if _client is None:
        _client = SentimentAPIClient()
    return _client
