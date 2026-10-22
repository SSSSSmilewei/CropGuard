#include <WiFi.h>
#include <WebServer.h>

// ============ 修改手机热点信息 ============
const char* ssid     = "vivoX300";
const char* password = "12345678";
// ===========================================

const int relayPin = 22;    //继电器IN脚
const int simKeyPin = 23;   //雾化板S引脚

WebServer server(80);

bool mistRunning = false;
bool isTimedMode = false;    //标记是否为定时模式
unsigned long mistStartTick = 0;
unsigned long mistDuration = 0;  //设定喷雾时长(ms)

//模拟按键脉冲
void pressMistKey(){
  digitalWrite(simKeyPin, LOW);
  delay(200);
  digitalWrite(simKeyPin, HIGH);
}

//网页HTML页面
const char htmlPage[] PROGMEM = R"HTML(
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
*{font-size:22px;}
button{padding:15px;margin:8px;width:240px;}
input{padding:10px;width:120px;}
</style>
</head>
<body>
<h2>ESP32 雾化控制器</h2>

<div>
设定定时喷雾时长：<input type="number" id="secInput" placeholder="单位：秒" min="1" value="30"> 秒
</div>
<br>
<button onclick="startTimer()">⏱️ 定时开启雾化</button>
<br>
<button onclick="location.href='/startDirect'">▶️ 立即开始雾化（持续喷雾，不会自动停）</button>
<br>
<button onclick="location.href='/stop'">⏹️ 立即关闭雾化</button>
<p id="status">%STATUS%</p>

<script>
function startTimer(){
  let t = document.getElementById("secInput").value;
  location.href="/start?time="+t;
}
</script>
</body>
</html>
)HTML";

void handleRoot() {
  String page = String(htmlPage);
  String statusText;
  if(mistRunning){
    if(isTimedMode){
      unsigned long now = millis();
      unsigned long remain = (mistDuration - (now - mistStartTick)) / 1000;
      if(remain <0) remain=0;
      statusText = "✅【定时模式】正在雾化，剩余：" + String(remain) + " 秒";
    }else{
      statusText = "✅【持续模式】正在雾化，不会自动停止，请手动关闭";
    }
  }else{
    statusText = "❌空闲，等待启动";
  }
  page.replace("%STATUS%", statusText);
  server.send(200, "text/html", page);
}

// 定时启动
void handleStartTimer(){
  if(mistRunning){
    server.send(200,"text/html","<h3>雾化正在运行中，请先关闭！</h3><a href='/'>返回</a>");
    return;
  }
  int sec = 30;
  if(server.hasArg("time")){
    sec = server.arg("time").toInt();
    if(sec <1) sec =1;
  }
  mistDuration = sec * 1000UL;

  //开启雾化流程
  digitalWrite(relayPin, LOW);
  delay(1000);
  pressMistKey();

  mistRunning = true;
  isTimedMode = true;
  mistStartTick = millis();

  server.send(200,"text/html","<h3>✅定时雾化已启动</h3><a href='/'>返回</a>");
}

// 立即持续开启（不会自动关闭）
void handleStartDirect(){
  if(mistRunning){
    server.send(200,"text/html","<h3>雾化正在运行中，请先关闭！</h3><a href='/'>返回</a>");
    return;
  }
  digitalWrite(relayPin, LOW);
  delay(1000);
  pressMistKey();

  mistRunning = true;
  isTimedMode = false;
  server.send(200,"text/html","<h3>✅持续雾化已开启，需要手动点关闭！</h3><a href='/'>返回</a>");
}

//停止雾化
void handleStop(){
  digitalWrite(relayPin, HIGH);
  mistRunning = false;
  isTimedMode = false;
  server.send(200,"text/html","<h3>❌雾化已关闭</h3><a href='/'>返回</a>");
}

void setup() {
  pinMode(relayPin, OUTPUT);
  pinMode(simKeyPin, OUTPUT);

  digitalWrite(relayPin, HIGH);
  digitalWrite(simKeyPin, HIGH);

  Serial.begin(115200);
  WiFi.begin(ssid, password);
  Serial.print("连接手机热点");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi成功！IP：" + WiFi.localIP().toString());

  server.on("/", handleRoot);
  server.on("/start", handleStartTimer);
  server.on("/startDirect", handleStartDirect);
  server.on("/stop", handleStop);
  server.begin();
}

void loop() {
  server.handleClient();

  //只有定时模式才判断倒计时
  if(mistRunning && isTimedMode){
    unsigned long now = millis();
    if( now - mistStartTick >= mistDuration ){
      digitalWrite(relayPin, HIGH);
      mistRunning = false;
      isTimedMode = false;
      Serial.println("定时时间到，自动关闭雾化");
    }
  }
}
