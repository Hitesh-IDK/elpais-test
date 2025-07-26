from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from pathlib import Path
from os import path
from datetime import datetime
import os
import json
import requests
from collections import defaultdict
import pytest
import logging
from selenium.webdriver.support import expected_conditions as EC

# The webdriver management will be handled by the browserstack-sdk
# so this will be overridden and tests will run on browserstack
# without any changes to the test files!

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    "base_url": "https://elpais.com",
    "max_articles": 5,
    "timeout": 25,
    "selectors": {
        "notice": "[data-testid=notice]",
        "accept_cookies": "#didomi-notice-agree-button",
        "nav": "nav",
        "article_container": "main > div",
        "article_header": "h2",
        "article_content": "p",
        "article_image": "figure > a > img"
    }
}

class TestElPaisOpinion:
    
    @pytest.fixture(autouse=True)
    def setup_test_environment(self, driver):
        """Setup test environment for each test"""
        self.driver = driver
        self.api_key = os.getenv("GCP_API_KEY")
        assert self.api_key is not None, "GCP_API_KEY environment variable is required"
        
        # Create images directory with timestamp
        Path("images").mkdir(exist_ok=True)
        timestamp = str(datetime.now()).replace(" ", "_").replace(":", "-").split(".")[0]
        self.curr_path = path.join(".", "images", f"test_{timestamp}")
        Path(self.curr_path).mkdir(exist_ok=True)

    def test_opinion_page_navigation_and_extraction(self):
        """Main test: Navigate to opinion page and extract articles"""
        try:
            # Navigate to base URL
            self.driver.get(CONFIG["base_url"])
            
            # Handle cookie consent and navigate to opinion page
            self._handle_cookie_consent()
            self._navigate_to_opinion_page()
            
            # Extract and translate articles
            translated_headers = self._extract_and_translate_articles()
            
            # Validate results
            assert len(translated_headers) > 0, "Should extract at least one article"
            assert all(header.strip() for header in translated_headers), "All headers should be non-empty"
            
            # Perform word frequency analysis
            word_stats = self._analyze_word_frequency(translated_headers)
            
            # Log results
            logger.info(f"Successfully processed {len(translated_headers)} articles")
            self._log_word_analysis(word_stats)
            
            # Report success to BrowserStack
            self._report_success(word_stats['repeated_words'])
            
        except Exception as e:
            self._report_failure(str(e))
            raise

    def _handle_cookie_consent(self):
        """Handle cookie consent notice"""
        self.driver.implicitly_wait(CONFIG["timeout"])
        
        try:
            wait = WebDriverWait(self.driver, 10)
            notice_ele = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, CONFIG["selectors"]["notice"]))
            )
            
            accept_button = notice_ele.find_element(By.ID, "didomi-notice-agree-button")
            wait.until(lambda _: accept_button.text == "Accept")
            accept_button.click()
            
            logger.info("Cookie consent handled successfully")
            
        except TimeoutException:
            logger.info("Cookie notice not found or timed out, continuing...")
        except NoSuchElementException:
            logger.info("Cookie notice elements not found, continuing...")
        
        # Reset implicit wait for subsequent operations
        self.driver.implicitly_wait(2)

    def _navigate_to_opinion_page(self):
        """Navigate to the opinion section"""
        try:
            nav = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "nav"))
            )
            
            nav_elements = nav.find_elements(By.TAG_NAME, "a")
            assert len(nav_elements) > 2, "Navigation should have more than 2 elements"
            
            # Click on opinion link (second nav element)
            opinion_ele = nav_elements[1]
            opinion_ele.click()
            
            logger.info("Successfully navigated to opinion page")
            
        except (TimeoutException, NoSuchElementException) as e:
            raise AssertionError(f"Failed to navigate to opinion page: {e}")
        
    def _extract_and_translate_articles(self):
        """Extract articles and translate headers"""
        try:
            # Wait for article container to load
            article_container = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, CONFIG["selectors"]["article_container"]))
            )
            
            # Take screenshot of content
            self._save_screenshot(article_container)
            
            # Find articles
            articles = article_container.find_elements(By.TAG_NAME, "article")
            num_articles = min(CONFIG["max_articles"], len(articles))
            
            logger.info(f"Found {len(articles)} articles, processing {num_articles}")
            
            extracted_data = []
            headers = []
            
            for i in range(num_articles):
                article_data = self._extract_single_article(articles[i], i)
                if article_data:
                    extracted_data.append(article_data)
                    headers.append(article_data["header"])
            
            # Translate headers if any were extracted
            if headers:
                return self._translate_text(headers)
            else:
                raise AssertionError("No articles were successfully extracted")
                
        except TimeoutException:
            raise AssertionError("Timed out waiting for article container")
        
    def _extract_single_article(self, article, index):
        """Extract data from a single article"""
        try:
            header_ele = article.find_element(By.CSS_SELECTOR, CONFIG["selectors"]["article_header"])
            header = header_ele.text
            
            header_url = header_ele.find_element(By.TAG_NAME, "a").get_attribute("href")
            content = article.find_element(By.TAG_NAME, CONFIG["selectors"]["article_content"]).text
            
            # Extract image URL
            image_url = ""
            try:
                image_ele = article.find_element(By.CSS_SELECTOR, CONFIG["selectors"]["article_image"])
                image_url = image_ele.get_attribute("src") or image_ele.get_attribute("data-src")
                
                # Save image if URL exists
                if image_url:
                    self._save_image(image_url, index)
                    
            except NoSuchElementException:
                logger.warning(f"No image found for article {index}")
            
            return {
                "header": header,
                "headerURL": header_url,
                "imageURL": image_url,
                "content": content
            }
            
        except NoSuchElementException as e:
            logger.error(f"Error extracting article {index}: {e}")
            return None
        
    def _save_screenshot(self, element):
        """Save screenshot of the article container"""
        try:
            browser_path = self._get_browser_path()
            screenshot_path = path.join(browser_path, "content_screenshot.png")
            element.screenshot(screenshot_path)
            logger.info(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            logger.error(f"Error saving screenshot: {e}")

    def _save_image(self, url, index):
        """Save article image"""
        try:
            response = requests.get(url, stream=True, timeout=10)
            response.raise_for_status()
            
            browser_path = self._get_browser_path()
            image_path = path.join(browser_path, f"article_{index}.jpg")
            
            with open(image_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"Image saved: {image_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving image {index}: {e}")
            return False
        
    def _get_browser_path(self):
        """Get browser-specific path for saving files"""
        try:
            caps = self.driver.capabilities
            browser_name = caps.get('browserName', 'unknown').lower()
            browser_version = caps.get('browserVersion', caps.get('version', ''))
            platform_name = caps.get('platformName', caps.get('platform', 'unknown'))
            
            folder_name = f"{browser_name}_{platform_name}".replace(" ", "_").lower()
            if browser_version:
                folder_name += f"_{browser_version.split('.')[0]}"
                
        except Exception:
            folder_name = "unknown_browser"
        
        browser_path = path.join(self.curr_path, folder_name)
        Path(browser_path).mkdir(exist_ok=True)
        return browser_path
    
    def _translate_text(self, texts):
        """Translate texts using Google Cloud Translation API"""
        if not texts:
            return []
            
        req_url = f"https://translation.googleapis.com/language/translate/v2?key={self.api_key}"
        parameters = {
            "format": "text",
            "q": texts,
            "target": "en",
            "source": "es"
        }
        
        try:
            response = requests.post(req_url, json=parameters, timeout=30)
            response.raise_for_status()
            
            data = response.json().get("data")
            assert data is not None, "No data returned from translation API"
            
            translations = [item.get("translatedText") for item in data.get("translations", [])]
            return translations
            
        except requests.RequestException as e:
            raise AssertionError(f"Translation API request failed: {e}")
        
    def _analyze_word_frequency(self, headers):
        """Analyze word frequency in headers"""
        count = defaultdict(int)
        
        for header in headers:
            words = header.split(" ")
            for word in words:
                clean_word = word.strip(".,!?;:\"'()[]{}").lower()
                if clean_word:
                    count[clean_word] += 1
        
        repeated_words = {key: cnt for key, cnt in count.items() if cnt > 1}
        unique_words = [key for key, cnt in count.items() if cnt == 1]
        
        return {
            "repeated_words": repeated_words,
            "unique_words": unique_words,
            "total_words": len(count)
        }
    
    def _log_word_analysis(self, word_stats):
        """Log word frequency analysis results"""
        logger.info("-----------------Repeated Words-----------------")
        for key, cnt in word_stats["repeated_words"].items():
            logger.info(f"{key}: {cnt}")
        
        logger.info("--------------------Unique Words--------------------")
        logger.info(", ".join(word_stats["unique_words"]))

    def _report_success(self, repeated_words):
        """Report test success to BrowserStack"""
        try:
            self.driver.execute_script(
                'browserstack_executor: {"action": "setSessionStatus", "arguments": {"status":"passed", "reason": ' + 
                json.dumps(repeated_words) + '}}'
            )
        except Exception as e:
            logger.error(f"Error reporting success to BrowserStack: {e}")

    def _report_failure(self, error_message):
        """Report test failure to BrowserStack"""
        try:
            self.driver.execute_script(
                'browserstack_executor: {"action": "setSessionStatus", "arguments": {"status":"failed", "reason": ' + 
                json.dumps(error_message) + '}}'
            )
        except Exception as e:
            logger.error(f"Error reporting failure to BrowserStack: {e}")