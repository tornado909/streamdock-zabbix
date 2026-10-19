"""Optional full browser test with entirely fake Zabbix results.

Requires: pip install playwright && playwright install chromium.
Never accesses a real Zabbix server or the user's Windows profile.
"""
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, parse_qs

try:
    from playwright.sync_api import sync_playwright
    from PIL import Image
except ImportError:
    print("OPTIONAL: playwright/Pillow missing; skip browser UI test")
    sys.exit(0)

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/"plugin"/"com.streamdock.zabbix.sdPlugin"
WS_MOCK = """
window.__events=[];
window.__frames={};
window.__currentSettings={};
class FakeSocket {
  constructor(uri) {
    window.__socket=this;
    this.readyState=1;
    setTimeout(()=>this.onopen?.(),10);
  }
  send(serialized) {
    const msg=JSON.parse(serialized);
    window.__events.push(msg);
    if(msg.event==='registerPropertyInspector'){
      setTimeout(()=>this.onmessage?.({data:JSON.stringify({
        event:'didReceiveSettings', payload:{settings:window.__currentSettings}
      })}),15);
    } else if(msg.event==='registerPlugin'){
      setTimeout(()=>this.onmessage?.({data:JSON.stringify({
        event:'willAppear',action:'com.streamdock.zabbix.widget',context:'status-key',
        payload:{settings:{dashboardId:'2',pageId:'201',widgetId:'2001',customLabel:''}}
      })}),20);
      setTimeout(()=>this.onmessage?.({data:JSON.stringify({
        event:'willAppear',action:'com.streamdock.zabbix.widget',context:'temp-key',
        payload:{settings:{dashboardId:'1',pageId:'101',widgetId:'1001',customLabel:''}}
      })}),35);
    } else if(msg.event==='setImage'){
      (window.__frames[msg.context] ||= []).push(msg.payload.image);
    }
  }
}
FakeSocket.OPEN=1;
window.WebSocket=FakeSocket;
"""
def reply(route):
    path = urlsplit(route.request.url)
    args = parse_qs(path.query)
    if path.path.endswith("/catalog/dashboards"):
        data = {"dashboards":[{"dashboardId":"1","name":"Operations"},{"dashboardId":"2","name":"Test lab"}]}
    elif path.path.endswith("/catalog/pages"):
        which = args["dashboard_id"][0]
        data = {"pages":[{"pageId":"101","name":"Overview","widgetsCount":2}] if which=="1"
                         else [{"pageId":"201","name":"Devices","widgetsCount":1}]}
    elif path.path.endswith("/catalog/widgets"):
        which = args["dashboard_id"][0]
        data = {"widgets":[{"widgetId":"1001","itemId":"5001","resolved":True,
                             "name":"Device temperature","host":"Demo Node","itemName":"Temperature","kind":"metric"}]
                if which=="1" else
                [{"widgetId":"2001","itemId":"5002","resolved":True,
                  "name":"System health","host":"Demo Node","itemName":"Health","kind":"status_item"}]}
    elif path.path.endswith("/render"):
        data={"connected":True,"updated_at":1,"tiles":{}}
        for key in args["keys"][0].split(","):
            status = key=="2:201:2001"
            data["tiles"][key] = {
                "label":"System health" if status else "Device temperature",
                "state":"problem" if status else "ok",
                "kind":"status_item" if status else "metric",
                "display":"" if status else "39",
                "detail":"PROBLEM" if status else "",
                "color":"#FF0000" if status else "#4CAF50",
                "url":"https://zabbix.example.com/zabbix.php?action=dashboard.view&dashboardid="+key.split(":")[0],
            }
    else:
        route.fulfill(status=404,body="{}")
        return
    route.fulfill(status=200,content_type="application/json",headers={"Access-Control-Allow-Origin":"null"},
                  body=json.dumps(data))

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True, args=["--no-sandbox","--disable-gpu"])
    try:
        inspector=browser.new_page(viewport={"width":380,"height":850})
        inspector.route("**/api/**",reply)
        inspector.add_init_script(script=WS_MOCK)
        errors=[]
        inspector.on("pageerror",lambda e:errors.append(str(e)))
        inspector.goto((PLUGIN/"inspector.html").as_uri())
        inspector.evaluate("""() => connectElgatoStreamDeckSocket(
           5432,'uuid','registerPropertyInspector','{}',
           JSON.stringify({context:'settings-key',action:'com.streamdock.zabbix.widget'})
        )""")
        inspector.wait_for_function("() => document.querySelector('#dashboards').options.length === 3")
        inspector.select_option("#dashboards","2")
        inspector.wait_for_function("() => document.querySelector('#widgets').value !== '' || document.querySelector('#widgets').options.length > 1")
        inspector.select_option("#widgets","2001")
        inspector.fill("#customLabel","Test health")
        inspector.locator("#apply").click()
        saved=inspector.evaluate("window.__events.filter(x=>x.event==='setSettings')")
        assert saved and saved[-1]["payload"]["dashboardId"]=="2"
        assert saved[-1]["payload"]["pageId"]=="201"
        assert saved[-1]["payload"]["widgetId"]=="2001"
        assert saved[-1]["payload"]["customLabel"]=="Test health"
        inspector.fill("#dashboardId","1")
        inspector.locator("#openDashboard").click()
        inspector.wait_for_function("() => document.querySelector('#pages').value === '101'")
        print("PASS inspector: catalog, manual ID, page and widget, per-button save")
        self_ru=browser.new_page(locale="ru-RU")
        self_ru.add_init_script(script=WS_MOCK)
        self_ru.goto((PLUGIN/"inspector.html").as_uri())
        assert self_ru.locator("h3").inner_text().find("Zabbix")>=0
        assert self_ru.locator("h3").inner_text() != "Zabbix · Item value"
        self_ru.close()
        print("PASS: English/Russian inspector localization")

        display=browser.new_page()
        display.route("**/api/**",reply)
        display.add_init_script(script=WS_MOCK)
        display.goto((PLUGIN/"plugin.html").as_uri())
        display.evaluate("() => connectElgatoStreamDeckSocket(5432,'uuid','registerPlugin','{}')")
        display.wait_for_function("""() => window.__frames['status-key']?.length >= 2 && window.__frames['temp-key']?.length >= 2""",timeout=15000)
        frames=display.evaluate("window.__frames")
        for key,expected in (("status-key",(255,0,0)),("temp-key",(76,175,80))):
            image=Image.open(BytesIO(base64.b64decode(frames[key][-1].split(",",1)[1]))).convert("RGB")
            assert image.size==(144,144)
            assert image.getpixel((1,1))==expected,(key,image.getpixel((1,1)))
        print("PASS buttons: 144px image, actual Zabbix threshold colors")
        assert not errors,errors
    finally:
        browser.close()
print("PASS public release headless UI acceptance")
