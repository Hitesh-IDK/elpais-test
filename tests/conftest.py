import pytest
from selenium import webdriver

@pytest.fixture(scope="function")
def driver(request):
    driver = webdriver.Chrome()
    
    def fin():
        driver.quit()
    
    request.addfinalizer(fin)
    return driver