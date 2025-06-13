/*
 MLX90640 thermal camera connected to a SparkFun Thing Plus - ESP32 WROOM

 Created by: Christopher Black
 */

#include <ESPmDNS.h>
#include <WebSocketsServer.h>
#include <WiFi.h>
#include <Wire.h>  // Used for I2C communication
#include "MLX90640_API.h"
#include "MLX90640_I2C_Driver.h"

// WiFi variables
WiFiServer server(80);
const char* wifi_ssid = "room101";
const char* wifi_pw = "noahzhang0";

// declare socket related variables
WebSocketsServer webSocket = WebSocketsServer(81);

// MLX90640 variables
#define TA_SHIFT -64  // Default shift for MLX90640 in open air is 8
static float mlx90640To[768];

// Used to compress data to the client
const char positive[27] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const char negative[27] = "abcdefghijklmnopqrstuvwxyz";

TaskHandle_t TaskA;
/* this variable hold queue handle */
xQueueHandle xQueue;

int total = 0;

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println();
    Serial.print("Connecting to ");
    Serial.println(wifi_ssid);

    // Connect to the WiFi network
    WiFi.begin(wifi_ssid, wifi_pw);
    WiFi.setHostname("esp32_thermal");
    int retry = 0;
    while (WiFi.status() != WL_CONNECTED) {
        delay(1000);
        retry += 1;
        Serial.print(".");
        if (retry > 4) {
            // Retry after 5 seconds
            Serial.println("");
            WiFi.begin(wifi_ssid, wifi_pw);
            retry = 0;
        }
    }

    Serial.println("");
    Serial.println("WiFi connected.");
    Serial.println("IP address: ");
    Serial.println(WiFi.localIP());

    if (!MDNS.begin("thermal")) {
        Serial.println("Error setting up MDNS responder!");
    } else {
        MDNS.addService("http", "tcp", 80);
        MDNS.addService("ws", "tcp", 81);
        Serial.println("mDNS responder started");
    }

    server.begin();

    xQueue = xQueueCreate(1, sizeof(mlx90640To));
    xTaskCreatePinnedToCore(
        Task1,       /* pvTaskCode */
        "Workload1", /* pcName */
        100000,      /* usStackDepth */
        NULL,        /* pvParameters */
        1,           /* uxPriority */
        &TaskA,      /* pxCreatedTask */
        0);          /* xCoreID */
    xTaskCreate(
        receiveTask,   /* Task function. */
        "receiveTask", /* name of task. */
        10000,         /* Stack size of task */
        NULL,          /* parameter of the task */
        1,             /* priority of the task */
        NULL);         /* Task handle to keep track of created task */

    webSocket.begin();
    webSocket.onEvent(webSocketEvent);
}

void loop() {
    webSocket.loop();

    WiFiClient client = server.available();  // listen for incoming clients

    if (!client) return;  // if no client, return

    Serial.println("New Client.");
    String currentLine = "";
    while (client.connected()) {
        if (client.available()) {
            char c = client.read();
            Serial.write(c);
            if (c == '\n') {
                // if the current line is blank, you got two newline characters in a row.
                // that's the end of the client HTTP request, so send a response:
                if (currentLine.length() == 0) {
                    // HTTP headers always start with a response code (e.g. HTTP/1.1 200 OK)
                    // and a content-type so the client knows what's coming, then a blank line:
                    client.println("HTTP/1.1 200 OK\r\nContent-type:application/json\r\nConnection: close\r\n");
                    client.println();

                    // Construct JSON response
                    String jsonResponse = "{\"ipAddress\":\"";
                    jsonResponse += WiFi.localIP().toString();
                    jsonResponse += "\", \"message\":\"Thermal camera server is active\"}";

                    client.print(jsonResponse);
                    client.println(); // End of JSON response body
                    // The HTTP response ends with another blank line (already sent by previous client.println())
                    // break out of the while loop:
                    break;
                } else {  // if you got a newline, then clear currentLine:
                    currentLine = "";
                }
            } else if (c != '\r') {  // if you got anything else but a carriage return character,
                currentLine += c;    // add it to the end of the currentLine
            }
        }
    }
    // close the connection:
    client.stop();
    Serial.println("Client Disconnected.");
}

// Capture thermal image on a different thread
void Task1(void* parameter) {
    int tick = 0;
    const byte MLX90640_address = 0x33;  // Default 7-bit unshifted address of the MLX90640

    Wire.setClock(800000L);
    Wire.begin();

    paramsMLX90640 mlx90640;
    Wire.beginTransmission((uint8_t)MLX90640_address);
    if (Wire.endTransmission() != 0) {
        Serial.println("MLX90640 not detected at default I2C address. Please check wiring. Freezing.");
        while (1)
            ;
    }

    // Get device parameters - We only have to do this once
    int status;
    uint16_t eeMLX90640[832];
    status = MLX90640_DumpEE(MLX90640_address, eeMLX90640);

    if (status != 0) {
        Serial.println("Failed to load system parameters");
    }
    status = MLX90640_ExtractParameters(eeMLX90640, &mlx90640);
    if (status != 0) {
        Serial.println("Parameter extraction failed");
    }
    MLX90640_SetRefreshRate(MLX90640_address, 0x05); // for 8 fps
    Wire.setClock(1000000L);
    float mlx90640Background[768];
    // const TickType_t xDelay = 125 / portTICK_PERIOD_MS;  // Corrected for 8Hz (1000ms / 8 = 125ms)
    for (;;) {
        //      String startMessage = "Capturing thermal image on core ";
        //      startMessage.concat(xPortGetCoreID());
        //      Serial.println( startMessage );
        //      long startTime = millis();
        for (byte x = 0; x < 2; x++)  // Read both subpages
        {
            uint16_t mlx90640Frame[834];
            int status = MLX90640_GetFrameData(MLX90640_address, mlx90640Frame);
            if (status < 0) {
                Serial.print("GetFrame Error: ");
                Serial.println(status);
            }

            float vdd = MLX90640_GetVdd(mlx90640Frame, &mlx90640);
            float Ta = MLX90640_GetTa(mlx90640Frame, &mlx90640);

            float tr = Ta - TA_SHIFT;  // Reflected temperature based on the sensor ambient temperature
            float emissivity = 0.95;

            MLX90640_CalculateTo(mlx90640Frame, &mlx90640, emissivity, tr, mlx90640Background);
        }
        //      long stopReadTime = millis();
        //      Serial.print("Read rate: ");
        //      Serial.print( 1000.0 / (stopReadTime - startTime), 2);
        //      Serial.println(" Hz");
        /* time to block the task until the queue has free space */
        const TickType_t xTicksToWait = pdMS_TO_TICKS(100);
        xQueueSendToFront(xQueue, &mlx90640Background, xTicksToWait);
        const TickType_t xDelay = 10 / portTICK_PERIOD_MS; // 8 Hz is 1/8 second
        vTaskDelay(xDelay);
    }
}

void receiveTask(void* parameter) {
    /* keep the status of receiving data */
    BaseType_t xStatus;
    /* time to block the task until data is available */
    const TickType_t xTicksToWait = pdMS_TO_TICKS(100);
    for (;;) {
        /* receive data from the queue */
        xStatus = xQueueReceive(xQueue, &mlx90640To, xTicksToWait);
        /* check whether receiving is ok or not */
        if (xStatus == pdPASS) {
            compressAndSend();
            total += 1;
        }
    }
    vTaskDelete(NULL);
}

void webSocketEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {
        case WStype_DISCONNECTED:
            Serial.println("Socket Disconnected.");
            break;
        case WStype_CONNECTED: {
            IPAddress ip = webSocket.remoteIP(num);
            Serial.println("Socket Connected.");
            // send message to client
            webSocket.sendTXT(num, "{\"message\":\"Connected\"}");
        } break;
        case WStype_TEXT:
            // send message to client
            break;
        case WStype_BIN:
        case WStype_ERROR:
        case WStype_FRAGMENT_TEXT_START:
        case WStype_FRAGMENT_BIN_START:
        case WStype_FRAGMENT:
        case WStype_FRAGMENT_FIN:
            break;
    }
}

// Some precision is lost during compression but data transfer speeds are
// much faster. We're able to get a higher frame rate by compressing data.
void compressAndSend() {
    String resultText = "";
    int numDecimals = 1;
    float powerOf10 = pow(10, numDecimals);  // Pre-calculate pow
    int accuracy = 8;
    int previousValue = round(mlx90640To[0] * powerOf10);
    previousValue = previousValue - (previousValue % accuracy);
    resultText.concat(numDecimals);
    resultText.concat(accuracy);
    resultText.concat(previousValue);
    resultText.concat(".");
    char currentLetter = 'A';
    char previousLetter = 'A';
    int letterCount = 1;
    int columnCount = 32;

    for (int x = 1; x < 768; x += 1) {
        int currentValue = round(mlx90640To[x] * powerOf10);
        currentValue = currentValue - (currentValue % accuracy);
        if (x % columnCount == 0) {
            previousValue = round(mlx90640To[x - columnCount] * powerOf10);
            previousValue = previousValue - (previousValue % accuracy);
        }

        int diffIndex = (currentValue - previousValue) / accuracy;

        if (diffIndex > 25) {
            diffIndex = 25;
        } else if (diffIndex < -25) {
            diffIndex = -25;
        }

        if (diffIndex >= 0) {
            currentLetter = positive[diffIndex];
        } else {
            currentLetter = negative[abs(diffIndex)];
        }

        if (x == 1) {
            previousLetter = currentLetter;
        } else if (currentLetter != previousLetter) {
            if (letterCount == 1) {
                resultText.concat(previousLetter);
            } else {
                resultText.concat(letterCount);
                resultText.concat(previousLetter);
            }
            previousLetter = currentLetter;
            letterCount = 1;
        } else {
            letterCount += 1;
        }

        previousValue = currentValue;
    }
    if (letterCount == 1) {
        resultText.concat(previousLetter);
    } else {
        resultText.concat(letterCount);
        resultText.concat(previousLetter);
    }
    // Wrap the resultText in a JSON object
    String jsonPacket = "{\"data\":\"" + resultText + "\"}";
    webSocket.broadcastTXT(jsonPacket);
}
