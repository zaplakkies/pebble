// Pebble screen-time board for the LilyGO T5 V2.3.1 (2.13", 250x122).
//
// Wakes every REFRESH_MIN minutes (or on a button press), joins the stronger of the
// two Wi-Fi networks, reads the server's /board.json and shows each kid's time today
// and when each of their devices last synced. Sleeps in between.
//
// If the server can't be reached it keeps showing the last data it got, marked old.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <driver/gpio.h>
#include <esp_sleep.h>

#include <GxEPD2_BW.h>
#include <U8g2_for_Adafruit_GFX.h>

#include "site.h"

#define PIN_EPD_CS 5
#define PIN_EPD_DC 17
#define PIN_EPD_RST 16
#define PIN_EPD_BUSY 4
#define PIN_EPD_SCK 18
#define PIN_EPD_MOSI 23
#define PIN_BUTTON 39
#define PIN_BATTERY 35

#define DISPLAY_ROTATION 1  // 1 or 3 (landscape, flipped)
#define REFRESH_MIN 5
#define FULL_REFRESH_EVERY 12  // wakes; a full refresh clears e-paper ghosting
#define WIFI_TIMEOUT_MS 15000
#define HTTP_TIMEOUT_MS 8000
#define BATTERY_LOW_MV 3450

#ifndef EPD_DRIVER
#define EPD_DRIVER GxEPD2_213_BN
#endif

GxEPD2_BW<EPD_DRIVER, EPD_DRIVER::HEIGHT> display(
    EPD_DRIVER(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));
U8G2_FOR_ADAFRUIT_GFX u8g2;

// Survives deep sleep, not a reset or power loss.
RTC_DATA_ATTR bool warm = false;
RTC_DATA_ATTR uint8_t wakes = 0;
RTC_DATA_ATTR char lastBody[3072] = "";  // last good /board.json
RTC_DATA_ATTR uint8_t staleWakes = 0;     // wakes since lastBody was fetched

static char network[33] = "";

// -------------------------------------------------------------------- fetch

static bool connectWifi() {
  WiFiMulti multi;
  if (WIFI1_SSID[0]) multi.addAP(WIFI1_SSID, WIFI1_PASS);
  if (WIFI2_SSID[0]) multi.addAP(WIFI2_SSID, WIFI2_PASS);
  WiFi.mode(WIFI_STA);
  // run() scans and joins the strongest known network.
  uint32_t t0 = millis();
  while (multi.run(5000) != WL_CONNECTED) {
    if (millis() - t0 > WIFI_TIMEOUT_MS) return false;
  }
  strlcpy(network, WiFi.SSID().c_str(), sizeof(network));
  Serial.printf("Wi-Fi %s, %d dBm, %s\n", network, WiFi.RSSI(),
                WiFi.localIP().toString().c_str());
  return true;
}

// Returns true and fills lastBody when the server answered with valid JSON.
static bool fetchBoard() {
  bool ok = false;
  if (connectWifi()) {
    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.begin(BOARD_URL);
    int code = http.GET();
    if (code == 200) {
      String body = http.getString();
      JsonDocument doc;
      if (body.length() < sizeof(lastBody) && !deserializeJson(doc, body)) {
        strlcpy(lastBody, body.c_str(), sizeof(lastBody));
        ok = true;
      } else {
        Serial.printf("bad reply, %u bytes\n", body.length());
      }
    } else {
      Serial.printf("HTTP %d\n", code);
    }
    http.end();
  }
  WiFi.disconnect(true, false);
  WiFi.mode(WIFI_OFF);
  return ok;
}

// ------------------------------------------------------------------ format

// 0m, 45m, 2h, 3h32
static void fmtDuration(char *out, size_t n, long s) {
  long m = s / 60;
  if (m < 60) {
    snprintf(out, n, "%ldm", m);
  } else if (m % 60 == 0) {
    snprintf(out, n, "%ldh", m / 60);
  } else {
    snprintf(out, n, "%ldh%02ld", m / 60, m % 60);
  }
}

// now, 4m, 3h, 8d; "never" for a device that never synced
static void fmtAgo(char *out, size_t n, JsonVariantConst v, long extraS) {
  if (v.isNull()) {
    strlcpy(out, "never", n);
    return;
  }
  long s = v.as<long>() + extraS;
  if (s < 60) {
    strlcpy(out, "now", n);
  } else if (s < 3600) {
    snprintf(out, n, "%ldm", s / 60);
  } else if (s < 86400) {
    snprintf(out, n, "%ldh", s / 3600);
  } else {
    snprintf(out, n, "%ldd", s / 86400);
  }
}

// ----------------------------------------------------------------- display

static int readBatteryMv() {
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) sum += analogReadMilliVolts(PIN_BATTERY);
  return (int)(sum / 8) * 2;  // on-board 1:2 divider
}

static void textAt(int x, int baseline, const char *s) {
  u8g2.setCursor(x, baseline);
  u8g2.print(s);
}

static void textRight(int right, int baseline, const char *s) {
  textAt(right - u8g2.getUTF8Width(s), baseline, s);
}

// "Name 4m  Name 2d", shortening the longest names until the line fits.
static void deviceLine(char *out, size_t n, JsonArrayConst devices, long extraS, int maxW) {
  const int maxDevices = 4;
  char names[maxDevices][24], ago[maxDevices][8];
  int count = 0;
  for (JsonObjectConst d : devices) {
    if (count == maxDevices) break;
    strlcpy(names[count], d["name"] | "?", sizeof(names[count]));
    fmtAgo(ago[count], sizeof(ago[count]), d["last_seen_s"], extraS);
    count++;
  }
  while (true) {
    out[0] = 0;
    for (int i = 0; i < count; i++) {
      if (i) strlcat(out, "   ", n);
      strlcat(out, names[i], n);
      strlcat(out, " ", n);
      strlcat(out, ago[i], n);
    }
    if (u8g2.getUTF8Width(out) <= maxW) return;
    int longest = 0;
    for (int i = 1; i < count; i++) {
      if (strlen(names[i]) > strlen(names[longest])) longest = i;
    }
    size_t len = strlen(names[longest]);
    if (len <= 4) return;  // can't shorten further; let it clip
    names[longest][len - 2] = '.';
    names[longest][len - 1] = 0;
  }
}

static void drawMessage(const char *title, const char *l1, const char *l2 = "") {
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    u8g2.setForegroundColor(GxEPD_BLACK);
    u8g2.setBackgroundColor(GxEPD_WHITE);
    u8g2.setFont(u8g2_font_helvB14_tf);
    textAt(6, 30, title);
    u8g2.setFont(u8g2_font_helvR10_tf);
    textAt(6, 64, l1);
    textAt(6, 88, l2);
  } while (display.nextPage());
}

static void drawBoard(JsonDocument &doc, bool fresh, bool full) {
  const int W = display.width(), H = display.height();
  const int headerH = 13;
  JsonArrayConst kids = doc["kids"];
  int n = max((int)kids.size(), 1);
  int rowH = (H - headerH) / n;
  bool twoLines = rowH >= 24;
  // Device ages were measured when the data was fetched; add the time since.
  long extraS = (long)staleWakes * REFRESH_MIN * 60;
  int batteryMv = readBatteryMv();

  char header[48], right[40];
  snprintf(header, sizeof(header), "%s  %s", doc["date"] | "", doc["time"] | "--:--");
  if (!fresh) {
    snprintf(right, sizeof(right), "no update since %s", doc["time"] | "--:--");
  } else if (batteryMv > 1000 && batteryMv < BATTERY_LOW_MV) {
    strlcpy(right, "battery low", sizeof(right));
  } else {
    strlcpy(right, network, sizeof(right));
  }

  if (full) {
    display.setFullWindow();
  } else {
    display.setPartialWindow(0, 0, W, H);
  }
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    u8g2.setForegroundColor(GxEPD_BLACK);
    u8g2.setBackgroundColor(GxEPD_WHITE);
    u8g2.setFont(u8g2_font_helvB08_tf);
    textAt(2, 9, header);
    u8g2.setFont(u8g2_font_helvR08_tf);
    textRight(W - 2, 9, right);
    display.drawFastHLine(0, headerH - 1, W, GxEPD_BLACK);

    int y = headerH;
    for (JsonObjectConst kid : kids) {
      char used[12], limit[12], times[28];
      fmtDuration(used, sizeof(used), kid["used_s"] | 0L);
      if (kid["limit_s"].isNull()) {
        strlcpy(times, used, sizeof(times));
      } else {
        fmtDuration(limit, sizeof(limit), kid["limit_s"].as<long>());
        snprintf(times, sizeof(times), "%s / %s", used, limit);
      }
      const char *status = kid["status"] | "under";
      bool over = !strcmp(status, "over");
      bool near = !strcmp(status, "near");

      // Over the limit: the kid's line is inverted. Near it: a marker after the name.
      const int bandH = 14;
      if (over) {
        display.fillRect(0, y + 1, W, bandH, GxEPD_BLACK);
        u8g2.setForegroundColor(GxEPD_WHITE);
        u8g2.setBackgroundColor(GxEPD_BLACK);
      }
      u8g2.setFont(u8g2_font_helvB10_tf);
      char name[32];
      snprintf(name, sizeof(name), "%s%s", kid["name"] | "?", near ? "  (near limit)" : "");
      if (over) strlcat(name, "  (over)", sizeof(name));
      textAt(3, y + 12, name);
      textRight(W - 3, y + 12, times);
      u8g2.setForegroundColor(GxEPD_BLACK);
      u8g2.setBackgroundColor(GxEPD_WHITE);

      if (twoLines) {
        char line[96];
        u8g2.setFont(u8g2_font_helvR08_tf);
        deviceLine(line, sizeof(line), kid["devices"], extraS, W - 6);
        textAt(3, y + 24, line);
      }
      y += rowH;
      if (y + rowH > H + 1) break;
    }
    if (kids.size() == 0) {
      u8g2.setFont(u8g2_font_helvR10_tf);
      textAt(3, 40, "No kids set up on the server yet.");
    }
  } while (display.nextPage());
}

// ------------------------------------------------------------------- sleep

static void deepSleep() {
  display.hibernate();
  gpio_hold_en((gpio_num_t)PIN_EPD_RST);
  gpio_deep_sleep_hold_en();
  while (digitalRead(PIN_BUTTON) == LOW) delay(10);  // a held button would wake us at once
  esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_BUTTON, 0);
  esp_sleep_enable_timer_wakeup((uint64_t)REFRESH_MIN * 60 * 1000000ULL);
  warm = true;
  Serial.flush();
  esp_deep_sleep_start();
}

// -------------------------------------------------------------------- main

void setup() {
  Serial.begin(115200);
  gpio_hold_dis((gpio_num_t)PIN_EPD_RST);
  gpio_deep_sleep_hold_dis();
  pinMode(PIN_BUTTON, INPUT);

  bool cold = !warm;
  if (cold) {
    lastBody[0] = 0;
    wakes = 0;
  }
  Serial.printf("\nwake %u, cold %d\n", wakes, cold);

  SPI.begin(PIN_EPD_SCK, -1, PIN_EPD_MOSI, -1);
  display.init(0, cold, 10, false);
  display.setRotation(DISPLAY_ROTATION);
  u8g2.begin(display);
  u8g2.setFontMode(1);

  if (cold) drawMessage("Pebble", "Connecting to Wi-Fi...", WIFI1_SSID " / " WIFI2_SSID);

  bool fresh = fetchBoard();
  staleWakes = fresh ? 0 : min(staleWakes + 1, 250);

  JsonDocument doc;
  if (lastBody[0] && !deserializeJson(doc, lastBody)) {
    bool full = cold || wakes % FULL_REFRESH_EVERY == 0;
    drawBoard(doc, fresh, full);
  } else {
    drawMessage("Pebble", network[0] ? "Can't reach the server:" : "No Wi-Fi network found.",
                network[0] ? BOARD_URL : "Press the button to try again.");
  }
  wakes++;
  deepSleep();
}

void loop() {}
