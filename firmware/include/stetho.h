// Blip — "Stetho" channel: samples the IF output of a CW Doppler module
// (CDM324 24 GHz or HB100 10.5 GHz) through a MAX4466 microphone-amp board,
// cleans it up on the ESP32 (bump gate, emphasis, noise suppression, AGC —
// see audio_dsp.h) and sends it to:
//   * the phone, as small WebSocket packets (lowest latency the link allows)
//   * optionally 3.5 mm earphones, as 1-bit delta-sigma (I2S PDM) on one pin + RC filter
//   * optionally a MAX98357A-style I2S amplifier board and a small speaker
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// NOT A MEDICAL DEVICE. This is a hobby experiment in hearing chest motion.
//
// Why a separate module: the RD-03D's signal processing lives inside its
// S5KM312CL chip and only tracked targets come out of the UART, so it cannot
// be made into a stethoscope (see DESIGN_NOTES.md).
//
// Timing: the ADC runs in DMA ("continuous") mode at 8 kHz, so samples are
// evenly spaced whatever Wi-Fi is doing. A FreeRTOS task wakes every 64
// samples (8 ms), runs the DSP, writes the I2S output and queues packets that
// loop() sends to the phone.
#pragma once
#include <Arduino.h>
#include <ESP_I2S.h>
#include <esp_adc/adc_continuous.h>
#include <esp_adc/adc_cali.h>
#include <esp_adc/adc_cali_scheme.h>
#include <freertos/FreeRTOS.h>
#include <freertos/message_buffer.h>
#include "config.h"
#include "audio_dsp.h"
#include "lab.h"

enum StethoOut : uint8_t { OUT_NONE = 0, OUT_EARPHONE = 1, OUT_I2S_AMP = 2 };

struct StethoSettings {
  blipdsp::Params dsp;
  uint8_t out = OUT_NONE;   // StethoOut
  uint8_t outVol = 60;      // 0..100, for the local outputs only
};

// Packets to the phone (all little-endian):
//   'U' flags seq16 gain_dB(int8) ns_dB(int8) + AUDIO_FRAME x mu-law byte  processed audio, 8 kHz
//   ('A' with int16 samples is the older form; the page still plays both)
//   'V' flags seq16 0 0                         + VITALS_FRAME x int16  raw chest motion, 100 Hz
//   flags: bit0 bump active in this packet, bit1 output clipped, bit2 ADC near a rail
static const int AUDIO_FRAME  = STETHO_AUDIO_FRAME;   // samples (= bytes) per 'U' packet
static const int VITALS_FRAME = 10;                   // 100 ms at 100 Hz
static const int PKT_HDR = 6;

class Stetho {
 public:
  bool running() const { return running_; }
  uint32_t overruns() const { return overruns_; }
  uint32_t dropped() const { return dropped_; }
  // Diagnostics for the Stetho tab and the serial log.
  const char* error() const { return err_; }          // why start() failed, "" if it didn't
  uint32_t samples() const { return samples_; }       // ADC samples read since start
  uint32_t invalid() const { return invalid_; }       // samples the driver flagged as not ours
  bool levelInMv() const { return cali_ != nullptr; } // false: level is raw 0..4095 (no eFuse calibration)
  // ADC level on PIN_STETHO_I over the last ~0.5 s: min / average / max; -1 = no samples yet
  void level(int& mn, int& avg, int& mx) const { mn = lvMin_; avg = lvAvg_; mx = lvMax_; }
  // Timing of the audio task, measured on the node itself (cleared by clearStats() and at every start):
  //   dspUsAvg/Max : time to process one 64-sample (8 ms) block: DSP + packets + I2S write
  //   gapMaxMs     : longest time between two blocks becoming available (8 ms is perfect)
  //   readTimeouts : reads that returned nothing for 100 ms (the ADC delivered no data)
  //   readErrs     : other read errors (ADC DMA overflow shows up here)
  uint32_t blocks() const { return blocks_; }
  uint32_t dspUsAvg() const { return blocks_ ? (uint32_t)(dspUsSum_ / blocks_) : 0; }
  uint32_t dspUsMax() const { return dspUsMax_; }
  uint32_t gapMaxMs() const { return gapMaxUs_ / 1000; }
  uint32_t readTimeouts() const { return readTimeouts_; }
  uint32_t readErrs() const { return readErrs_; }
  void clearStats() { blocks_ = 0; dspUsSum_ = 0; dspUsMax_ = 0; gapMaxUs_ = 0; readTimeouts_ = 0; readErrs_ = 0; }

  // Settings may be changed from the web task; the audio task picks them up
  // at the next 8 ms block.
  void apply(const StethoSettings& s) {
    pending_ = s;
    dirty_ = true;
  }

  bool start(const StethoSettings& s) {
    if (running_) { apply(s); return true; }
    cur_ = s; pending_ = s; dirty_ = false;
    chain_.configure(cur_.dsp);
    if (!audioQ_) audioQ_ = xMessageBufferCreate((PKT_HDR + AUDIO_FRAME + 4) * 12);   // 12 packets ≈ 380 ms of slack
    if (!vitalsQ_) vitalsQ_ = xMessageBufferCreate((PKT_HDR + VITALS_FRAME * 2 + 4) * 8);
    err_[0] = 0; samples_ = 0; invalid_ = 0; lvMin_ = lvAvg_ = lvMax_ = -1;
    clearStats();
    outBegin(cur_.out);
    stopReq_ = false;
    adcState_ = 0;
    running_ = true;
    // The audio task opens the ADC itself (adcBegin() at the top of taskLoop) and
    // closes it itself. adc_continuous_start() takes a mutex that is held for as
    // long as sampling runs, and FreeRTOS asserts if a different task gives it
    // back: opening here (web/loop task) and closing in the audio task crashed the
    // node on every stop, seen in a bench-test log (assert xTaskPriorityDisinherit
    // <- adc_lock_release <- adc_continuous_stop <- Stetho::adcEnd).
    UBaseType_t prio = lab::f.prio >= 1 && lab::f.prio <= 24 ? lab::f.prio : 5;   // Lab switch; 5 unless changed
    if (xTaskCreate(&Stetho::taskEntry, "stetho", 8192, this, prio, &task_) != pdPASS) {
      task_ = nullptr; running_ = false; outEnd();
      snprintf(err_, sizeof err_, "could not start the audio task (out of memory)");
      return false;
    }
    for (int i = 0; i < 400 && adcState_ == 0; i++) delay(5);   // normally a few ms
    if (adcState_ != 1) {                                       // the task reports why in err_ and exits
      stopReq_ = true;
      for (int i = 0; i < 100 && task_; i++) delay(10);
      running_ = false;
      if (!err_[0]) snprintf(err_, sizeof err_, "ADC did not start in time");
      return false;
    }
    return true;
  }

  void stop() {
    if (!running_) return;
    stopReq_ = true;
    for (int i = 0; i < 50 && task_; i++) delay(10);     // task exits within one block
    running_ = false;
  }

  // Called from loop(): next packet for the phone, or 0 if none.
  size_t nextAudioPacket(uint8_t* dst, size_t cap) { return audioQ_ ? xMessageBufferReceive(audioQ_, dst, cap, 0) : 0; }
  // Same, but waits up to ms for one (used by the sender task).
  size_t waitAudioPacket(uint8_t* dst, size_t cap, uint32_t ms) { return audioQ_ ? xMessageBufferReceive(audioQ_, dst, cap, pdMS_TO_TICKS(ms)) : 0; }
  size_t nextVitalsPacket(uint8_t* dst, size_t cap) { return vitalsQ_ ? xMessageBufferReceive(vitalsQ_, dst, cap, 0) : 0; }
  // Throw away queued audio so a slow phone catches up instead of lagging.
  void flushAudio() { if (audioQ_) xMessageBufferReset(audioQ_); }

  // Output silence for the next ms milliseconds (DSP keeps running so it settles).
  void mute(uint32_t ms) { muteN_ = ms * (blipdsp::FS / 1000); }

  int gainDb() const { return gainDb_; }
  int nsDb() const { return nsDb_; }
  bool bump() const { return bumpNow_; }

 private:
  static const int BLOCK = 64;                       // 8 ms
  adc_continuous_handle_t adc_ = nullptr;
  I2SClass i2s_;
  bool i2sOn_ = false;
  uint8_t outMode_ = OUT_NONE;
  TaskHandle_t task_ = nullptr;
  MessageBufferHandle_t audioQ_ = nullptr, vitalsQ_ = nullptr;
  volatile bool running_ = false, stopReq_ = false, dirty_ = false;
  volatile uint8_t adcState_ = 0;                    // 0 opening, 1 sampling, 2 failed to open
  StethoSettings cur_, pending_;
  blipdsp::AudioChain chain_;
  blipdsp::Decimator dec_;
  int32_t dc_ = 2048 << 14;                          // DC tracker, Q14, ~2 s time constant
  uint32_t overruns_ = 0, dropped_ = 0;
  char err_[72] = "";
  volatile uint32_t samples_ = 0, invalid_ = 0;
  volatile uint32_t blocks_ = 0, dspUsMax_ = 0, gapMaxUs_ = 0, readTimeouts_ = 0, readErrs_ = 0;
  volatile uint64_t dspUsSum_ = 0;
  uint32_t synthPhase_ = 0, synthRng_ = 1;
  int osN_ = 1; bool nbCur_ = true;
  volatile int lvMin_ = -1, lvAvg_ = -1, lvMax_ = -1;
  int wMin_ = 4095, wMax_ = 0; uint32_t wSum_ = 0, wN_ = 0;
  adc_cali_handle_t cali_ = nullptr;
  volatile uint32_t muteN_ = 0;
  volatile int gainDb_ = 0, nsDb_ = 0; volatile bool bumpNow_ = false;

  // packet assembly
  uint8_t aPkt_[PKT_HDR + AUDIO_FRAME];  int aN_ = 0; uint16_t aSeq_ = 0; uint8_t aFlags_ = 0;
  uint8_t vPkt_[PKT_HDR + VITALS_FRAME * 2]; int vN_ = 0; uint16_t vSeq_ = 0; uint8_t vFlags_ = 0;

  bool adcBegin() {
    adc_continuous_handle_cfg_t hc = {};
    hc.max_store_buf_size = BLOCK * SOC_ADC_DIGI_RESULT_BYTES * (osN_ > 2 ? osN_ * 3 : 8);
    hc.conv_frame_size = BLOCK * SOC_ADC_DIGI_RESULT_BYTES;
    esp_err_t e = adc_continuous_new_handle(&hc, &adc_);
    if (e != ESP_OK) { adc_ = nullptr; snprintf(err_, sizeof err_, "ADC driver: %s", esp_err_to_name(e)); return false; }
    adc_unit_t unit; adc_channel_t ch;
    if (adc_continuous_io_to_channel(PIN_STETHO_I, &unit, &ch) != ESP_OK || unit != ADC_UNIT_1) {
      adcEnd(); snprintf(err_, sizeof err_, "GPIO%d is not an ADC1 pin", PIN_STETHO_I); return false;
    }
    adc_digi_pattern_config_t pat = {};
    pat.atten = ADC_ATTEN_DB_12;                     // ~0–2.5 V (C3) / ~0–3.1 V (S3)
    pat.channel = (uint8_t)ch;
    pat.unit = ADC_UNIT_1;
    pat.bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;
    adc_continuous_config_t cc = {};
    cc.pattern_num = 1;
    cc.adc_pattern = &pat;
    cc.sample_freq_hz = blipdsp::FS * osN_;           // Lab os: 1x as shipped, or 2/4/8x with a block average per sample
    cc.conv_mode = ADC_CONV_SINGLE_UNIT_1;
    cc.format = ADC_DIGI_OUTPUT_FORMAT_TYPE2;
    if ((e = adc_continuous_config(adc_, &cc)) != ESP_OK) { adcEnd(); snprintf(err_, sizeof err_, "ADC config: %s", esp_err_to_name(e)); return false; }
    if ((e = adc_continuous_start(adc_)) != ESP_OK) { adcEnd(); snprintf(err_, sizeof err_, "ADC start: %s", esp_err_to_name(e)); return false; }
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    // Only for showing the pin's voltage on the Stetho tab; the audio path uses raw counts.
    adc_cali_curve_fitting_config_t cf = {};
    cf.unit_id = ADC_UNIT_1; cf.chan = ch; cf.atten = ADC_ATTEN_DB_12; cf.bitwidth = ADC_BITWIDTH_12;
    if (adc_cali_create_scheme_curve_fitting(&cf, &cali_) != ESP_OK) cali_ = nullptr;
#endif
    return true;
  }
  void adcEnd() {
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    if (cali_) { adc_cali_delete_scheme_curve_fitting(cali_); cali_ = nullptr; }
#endif
    if (!adc_) return;
    adc_continuous_stop(adc_);
    adc_continuous_deinit(adc_);
    adc_ = nullptr;
  }

  void outBegin(uint8_t mode) {
    outEnd();
    outMode_ = mode;
    if (mode == OUT_EARPHONE) {
#if PIN_PDM_OUT >= 0
      // 1-bit delta-sigma stream (I2S peripheral in PDM mode). Only the data pin
      // is used; the clock pin is required by the driver and can stay unconnected.
      i2s_.setPinsPdmTx(PIN_I2S_BCLK, PIN_PDM_OUT);
      i2sOn_ = i2s_.begin(I2S_MODE_PDM_TX, blipdsp::FS, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
#endif
    } else if (mode == OUT_I2S_AMP) {
#if PIN_I2S_DOUT >= 0
      // MAX98357A and friends. Stereo with L = R so the board's (L+R)/2 default
      // and its left-only mode both get the full signal.
      i2s_.setPins(PIN_I2S_BCLK, PIN_I2S_WS, PIN_I2S_DOUT);
      i2sOn_ = i2s_.begin(I2S_MODE_STD, blipdsp::FS, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
#endif
    }
    if (!i2sOn_) outMode_ = OUT_NONE;
  }
  void outEnd() {
    if (i2sOn_) { i2s_.end(); i2sOn_ = false; }
    outMode_ = OUT_NONE;
  }

  static void taskEntry(void* arg) { static_cast<Stetho*>(arg)->taskLoop(); }

  // Lab source 1: a made-up chest at ADC level, integer maths only (no float, so it
  // costs about what the real ADC path costs and does not skew the CPU comparison).
  // 72 bpm "heart sound" bursts (45 Hz square, 70 ms) plus a little noise, around 2700.
  int32_t synthSample() {
    synthRng_ = synthRng_ * 1664525u + 1013904223u;
    int32_t noise = (int32_t)((synthRng_ >> 16) % 81) - 40;
    uint32_t p = synthPhase_++ % 6667;                    // 0.833 s
    int32_t burst = (p < 560) ? ((((p / 89) & 1) ? 300 : -300)) : 0;
    return 2700 + burst + noise;
  }

  void taskLoop() {
    const bool synth = lab::f.src == 1;               // Lab: made-up samples, ADC driver never opened
    osN_ = lab::osFactor();
    nbCur_ = true;
    if (!synth && !adcBegin()) {                      // err_ already says why
      adcState_ = 2;
      outEnd();
      running_ = false;
      task_ = nullptr;
      vTaskDelete(nullptr);
      return;
    }
    adcState_ = 1;
    adc_continuous_data_t raw[BLOCK];
    uint16_t acc[BLOCK * 8];                          // oversampled conversions of one block
    int16_t out[BLOCK * 2];
    TickType_t wake = xTaskGetTickCount();
    uint32_t lastBlockUs = 0;
    while (!stopReq_) {
      uint32_t n = 0;
      if (synth) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(1000 * BLOCK / blipdsp::FS));   // 8 ms
        for (int i = 0; i < BLOCK; i++) { raw[i].raw_data = (uint32_t)synthSample(); raw[i].valid = true; }
        n = BLOCK;
      } else {
        esp_err_t e = ESP_OK;
        if (osN_ <= 1) {
          e = adc_continuous_read_parse(adc_, raw, BLOCK, &n, 100);
        } else {                                       // several conversions per sample: collect them, then average each group
          uint32_t got = 0;
          while (got < (uint32_t)BLOCK * osN_ && !stopReq_) {
            uint32_t m = 0;
            e = adc_continuous_read_parse(adc_, raw, BLOCK, &m, 100);
            if (e != ESP_OK) break;
            for (uint32_t j = 0; j < m && got < (uint32_t)BLOCK * osN_; j++) { if (raw[j].valid) acc[got++] = (uint16_t)raw[j].raw_data; else invalid_ = invalid_ + 1; }
          }
          if (e == ESP_OK) { n = got / osN_; for (uint32_t i = 0; i < n; i++) { raw[i].raw_data = blipdsp::osMean(&acc[i * osN_], osN_); raw[i].valid = true; } }
        }
        if (e == ESP_ERR_TIMEOUT) { readTimeouts_ = readTimeouts_ + 1; continue; }
        if (e != ESP_OK) { overruns_++; readErrs_ = readErrs_ + 1; continue; }
      }
      uint32_t t0 = micros();
      if (lastBlockUs) { uint32_t gap = t0 - lastBlockUs; if (gap > gapMaxUs_) gapMaxUs_ = gap; }
      lastBlockUs = t0;
      const bool nbWant = lab::f.nb == 0;             // Lab: burst blanker on/off, live
      if (dirty_ || nbWant != nbCur_) {               // settings from the web page
        dirty_ = false;
        StethoSettings s = pending_;
        if (s.out != cur_.out) outBegin(s.out);
        blipdsp::Params q = s.dsp; q.blanker = nbWant;
        chain_.configure(q);
        cur_ = s; nbCur_ = nbWant;
      }
      int32_t vol = (int32_t)cur_.outVol * cur_.outVol * 32768 / 10000;   // squared = more natural taper
      int k = 0;
      for (uint32_t i = 0; i < n; i++) {
        if (!raw[i].valid) { invalid_ = invalid_ + 1; continue; }
        int32_t v = (int32_t)raw[i].raw_data;          // 0..4095
        samples_ = samples_ + 1;
        if (v < wMin_) wMin_ = v;
        if (v > wMax_) wMax_ = v;
        wSum_ += v;
        if (++wN_ >= (uint32_t)blipdsp::FS / 2) publishLevel();
        dc_ += ((v << 14) - dc_) >> 14;                // ~2 s DC tracker (removes the MAX4466's mid-rail bias)
        int32_t s = (v - (dc_ >> 14)) << 3;            // ±16384 full scale
        bool rail = v < 40 || v > 4055;

        int16_t vs;
        if (dec_.push(s, vs)) pushVitals(vs, rail);

        int16_t o;
        if (lab::f.dsp == 0) o = chain_.process(s);                       // shipped
        else if (lab::f.dsp == 1) o = (int16_t)(s > 32767 ? 32767 : s < -32768 ? -32768 : s);   // Lab: chain bypassed
        else o = 0;                                                       // Lab: silence
        if (muteN_) { muteN_ = muteN_ - 1; o = 0; }
        aFlags_ |= (chain_.bumpActive() ? 1 : 0) | (rail ? 4 : 0);
        pushAudio(o);
        int16_t lo = (int16_t)(((int32_t)o * vol) >> 15);
        if (outMode_ == OUT_I2S_AMP) { out[k * 2] = lo; out[k * 2 + 1] = lo; }
        else out[k] = lo;
        k++;
      }
      if (i2sOn_ && k) i2s_.write((uint8_t*)out, (size_t)k * (outMode_ == OUT_I2S_AMP ? 4 : 2));
      gainDb_ = chain_.gainDb(); nsDb_ = chain_.nsAttenDb(); bumpNow_ = chain_.bumpActive();
      uint32_t used = micros() - t0;
      blocks_ = blocks_ + 1; dspUsSum_ = dspUsSum_ + used; if (used > dspUsMax_) dspUsMax_ = used;
    }
    outEnd();
    adcEnd();
    task_ = nullptr;
    vTaskDelete(nullptr);
  }

  int toMv(int raw) const {
    int mv = raw;
    if (cali_ && adc_cali_raw_to_voltage(cali_, raw, &mv) != ESP_OK) mv = raw;
    return mv;
  }
  void publishLevel() {
    lvMin_ = toMv(wMin_); lvAvg_ = toMv((int)(wSum_ / wN_)); lvMax_ = toMv(wMax_);
    wMin_ = 4095; wMax_ = 0; wSum_ = 0; wN_ = 0;
  }

  void pushAudio(int16_t o) {
    aPkt_[PKT_HDR + aN_] = blipdsp::mulaw(o);
    if (++aN_ < AUDIO_FRAME) return;
    if (chain_.clippedAndClear()) aFlags_ |= 2;
    aPkt_[0] = 'U'; aPkt_[1] = aFlags_; aPkt_[2] = aSeq_ & 0xff; aPkt_[3] = aSeq_ >> 8;
    int g = chain_.gainDb(), d = chain_.nsAttenDb();
    aPkt_[4] = (uint8_t)(int8_t)(g < -127 ? -127 : g > 127 ? 127 : g);
    aPkt_[5] = (uint8_t)(int8_t)(d < -127 ? -127 : d);
    if (xMessageBufferSend(audioQ_, aPkt_, sizeof aPkt_, 0) != sizeof aPkt_) dropped_++;
    aSeq_++; aN_ = 0; aFlags_ = 0;
  }

  void pushVitals(int16_t v, bool rail) {
    memcpy(vPkt_ + PKT_HDR + vN_ * 2, &v, 2);
    vFlags_ |= (chain_.bumpActive() ? 1 : 0) | (rail ? 4 : 0);
    if (++vN_ < VITALS_FRAME) return;
    vPkt_[0] = 'V'; vPkt_[1] = vFlags_; vPkt_[2] = vSeq_ & 0xff; vPkt_[3] = vSeq_ >> 8; vPkt_[4] = 0; vPkt_[5] = 0;
    xMessageBufferSend(vitalsQ_, vPkt_, sizeof vPkt_, 0);
    vSeq_++; vN_ = 0; vFlags_ = 0;
  }
};
