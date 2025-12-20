
import pytest
from twscrape.xclid import get_scripts_list

def test_get_scripts_list_malformed_json():
    # Test case with various malformed JSON (unquoted keys, including no underscores and numeric)
    malformed_text_content = 'node_modules_pnpm_ws_8_18_0_node_modules_ws_browser_js:"12345",runtime:"67890",999:"000"'
    malformed_text = 'stuff... e=>e+"."+' + '{' + malformed_text_content + '}' + '[e]+"a.js"... stuff'
    
    scripts = list(get_scripts_list(malformed_text))
    
    assert len(scripts) == 3
    assert "https://abs.twimg.com/responsive-web/client-web/node_modules_pnpm_ws_8_18_0_node_modules_ws_browser_js.12345a.js" in scripts
    assert "https://abs.twimg.com/responsive-web/client-web/runtime.67890a.js" in scripts
    assert "https://abs.twimg.com/responsive-web/client-web/999.000a.js" in scripts

def test_get_scripts_list_normal_json():
    # Test case with normal JSON (quoted keys)
    normal_text_content = '"normal_key":"12345","another_key":"67890"'
    normal_text = 'stuff... e=>e+"."+' + '{' + normal_text_content + '}' + '[e]+"a.js"... stuff'
    
    scripts = list(get_scripts_list(normal_text))
    
    assert len(scripts) == 2
    assert "https://abs.twimg.com/responsive-web/client-web/normal_key.12345a.js" in scripts
    assert "https://abs.twimg.com/responsive-web/client-web/another_key.67890a.js" in scripts
