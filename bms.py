#!/usr/bin/env python3
import time
import threading
import requests
from datetime import datetime
from gpiozero import LED, Button, MotionSensor
from Freenove_DHT import DHT
from LCD1602 import CharLCD1602
from threading import Lock

# for writing onto LCD
lcd_lock = Lock()

# GPIO pin mappings
BUTTON_UP = 17
BUTTON_DOWN = 27
BUTTON_DOOR = 22
LED_GREEN = 23  # Lights
LED_RED = 24    # Heater
LED_BLUE = 25   # AC
DHT_PIN = 4
PIR_PIN = 5

# Initialize components
lcd = CharLCD1602()
dht = DHT(DHT_PIN)
pir = MotionSensor(PIR_PIN)
led_light = LED(LED_GREEN)
led_heat = LED(LED_RED)
led_ac = LED(LED_BLUE)
btn_up = Button(BUTTON_UP)
btn_down = Button(BUTTON_DOWN)
btn_door = Button(BUTTON_DOOR)

# System states
door_open = False
hvac_status = "OFF"  # "OFF", "HEAT", or "AC"
light_status = "OFF"
desired_temp = 72
temp_history = []
last_motion_time = time.time()
log_file = "log.txt"

# OpenWeatherMap API, replace with own key + city
API_KEY = "keyhere"
CITY = "Irvine"

# using API to get humidity 
def fetch_humidity():
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={API_KEY}&units=imperial"
        response = requests.get(url).json()
        return response['main']['humidity']
    except:
        return 50  # fallback

# logging events 
def log_event(event):
    timestamp = datetime.now().strftime("%H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"{timestamp} {event}\n")

# dht reading the temperature for weather index
def read_temperature():
    # try some times for reliability
    for _ in range(15):
        if dht.readDHT11() == 0:
            celsius = dht.getTemperature()
            fahrenheit = celsius * 9 / 5 + 32
            return round(fahrenheit)
        time.sleep(0.1)
    return None

# calculating the weather index
def get_feels_like(temp):
    humidity = fetch_humidity()
    return round(temp + 0.05 * humidity)

# updating the main LCD
def update_main_lcd(temp, feels_like):
    door_status = "O" if door_open else "C"
    # formatting
    line1 = f"{desired_temp}/{feels_like}       Dr:{door_status}"
    line2 = f"H:{hvac_status}       L:{light_status}"

    # Ensure each line is exactly 16 characters
    line1 = line1.ljust(16)[:16]
    line2 = line2.ljust(16)[:16]

    # thread for LCD updating
    with lcd_lock:
        lcd.clear()
        lcd.write(0, 0, line1)
        lcd.write(0, 1, line2)

# HVAC related msgs
def hvac_notify(message):
    lcd.clear()
    lcd.write(0, 0, message)
    time.sleep(3)

def set_hvac(temp, feels_like):
    global hvac_status

    # HVAC must be off if door is open or fire condition
    if door_open or feels_like >= 95:
        if hvac_status != "OFF":
            led_heat.off()
            led_ac.off()
            hvac_status = "OFF"
            log_event("HVAC OFF")
            # writing to LCD
            with lcd_lock:
                lcd.clear()
                lcd.write(0, 0, "HVAC OFF")
                time.sleep(3)
        return

    # Heater on
    if feels_like <= desired_temp - 3:
        if hvac_status != "HEAT":
            led_heat.on()
            led_ac.off()
            hvac_status = "HEAT"
            log_event("HVAC HEAT")
            with lcd_lock:
                lcd.clear()
                lcd.write(0, 0, "HVAC ON")
                time.sleep(3)
    # AC on
    elif feels_like >= desired_temp + 3:
        if hvac_status != "AC":
            led_ac.on()
            led_heat.off()
            hvac_status = "AC"
            log_event("HVAC AC")
            with lcd_lock:
                lcd.clear()
                lcd.write(0, 0, "HVAC ON")
                time.sleep(3)
    # HVAC off
    else:
        if hvac_status != "OFF":
            led_heat.off()
            led_ac.off()
            hvac_status = "OFF"
            log_event("HVAC OFF")
            with lcd_lock:
                lcd.clear()
                lcd.write(0, 0, "HVAC OFF")
                time.sleep(3)

# fire alarm function - flash all lights
def fire_alarm_mode():
    global door_open, hvac_status

    if hvac_status != "OFF":
        led_heat.off()
        led_ac.off()
        hvac_status = "OFF"
        log_event("HVAC OFF")

    if not door_open:
        door_open = True
        log_event("DOOR OPEN")

    lcd.clear()
    lcd.write(0, 0, "FIRE! DOOR OPEN")
    lcd.write(0, 1, "EVACUATE NOW!")
    log_event("FIRE ALARM")

    while True:
        # flashing all the lights 
        led_light.toggle()
        led_heat.toggle()
        led_ac.toggle()
        time.sleep(0.5)     # period = 1 sec, flash for half

        temp = read_temperature()
        if temp:
            temp_history.append(temp)
            if len(temp_history) > 3:
                temp_history.pop(0)
            avg_temp = round(sum(temp_history) / len(temp_history))
            feels_like = get_feels_like(avg_temp)
            if feels_like < 95: # adjust to 90 for testing
                break

    # drops below 95
    led_light.off()
    led_heat.off()
    led_ac.off()

    with lcd_lock:
        lcd.clear()
        lcd.write(0, 0, "Fire cleared")
        time.sleep(3)
    log_event("FIRE CLEARED")

    # looking at HVAC state again so proper LEDs are turned on
    if temp_history:
        avg_temp = round(sum(temp_history) / len(temp_history))
        feels_like = get_feels_like(avg_temp)
        set_hvac(avg_temp, feels_like)
        update_main_lcd(avg_temp, feels_like)

# green LED motion sensor
def motion_check():
    global light_status, last_motion_time
    while True:
        if pir.motion_detected:
            led_light.on()
            last_motion_time = time.time()
            if light_status != "ON":
                light_status = "ON"
                log_event("LIGHTS ON")
        elif time.time() - last_motion_time > 10:
            led_light.off()
            if light_status != "OFF":
                light_status = "OFF"
                log_event("LIGHTS OFF")
        time.sleep(0.1)

# door toggling for 3rd push button
def door_toggle():
    global door_open
    door_open = not door_open

    # proper messages onto lCD
    with lcd_lock:
        lcd.clear()
        if door_open:
            lcd.write(0, 0, "Window/DoorO")
            lcd.write(0, 1, "HVAC HALTED")
            log_event("DOOR OPEN")
            time.sleep(3)
        else:
            lcd.write(0, 0, "Window/DoorC")
            lcd.write(0, 1, "HVAC ON")
            log_event("DOOR CLOSED")
            time.sleep(3)

    # turn off system
    time.sleep(3)

    # for proper LED lighting again 
    if not door_open and temp_history:
        avg_temp = round(sum(temp_history) / len(temp_history))
        feels_like = get_feels_like(avg_temp)
        set_hvac(avg_temp, feels_like)
        update_main_lcd(avg_temp, feels_like)

# pushbutton to increase desired temp
def increase_temp():
    global desired_temp
    if desired_temp < 95:
        desired_temp += 1
        log_event(f"TEMP INCREASED TO {desired_temp}")
        # Force HVAC reevaluation and LCD refresh
        if temp_history:
            avg_temp = round(sum(temp_history) / len(temp_history))
            feels_like = get_feels_like(avg_temp)
            set_hvac(avg_temp, feels_like)
            update_main_lcd(avg_temp, feels_like)

# push button to decrease desired temp
def decrease_temp():
    global desired_temp
    if desired_temp > 65:
        desired_temp -= 1
        log_event(f"TEMP DECREASED TO {desired_temp}")
        # Force HVAC reevaluation and LCD refresh
        if temp_history:
            avg_temp = round(sum(temp_history) / len(temp_history))
            feels_like = get_feels_like(avg_temp)
            set_hvac(avg_temp, feels_like)
            update_main_lcd(avg_temp, feels_like)

############ main program #################
# initialize buttons
btn_door.when_pressed = door_toggle
btn_up.when_pressed = increase_temp
btn_down.when_pressed = decrease_temp

# motion detection thread
motion_thread = threading.Thread(target=motion_check)
motion_thread.daemon = True
motion_thread.start()

# initialize LCD 
lcd.init_lcd()
with open(log_file, "w"): pass  # clear previous log
print("Starting BMS...")

# main loop
try:
    while True:
        temp = read_temperature()
        if temp is not None:
            temp_history.append(temp)
            # keep only last 3 readings
            if len(temp_history) > 3:
                temp_history.pop(0)
            # averaging
            avg_temp = round(sum(temp_history) / len(temp_history))
            feels_like = get_feels_like(avg_temp)

            # over 95 degrees -> fire alarm. change for testing -> 90 
            if feels_like >= 95:
                fire_alarm_mode()
            else:
                set_hvac(avg_temp, feels_like)
                update_main_lcd(avg_temp, feels_like)
        # calls every 1 sec.
        time.sleep(1)

# to end the program, will get messages involving thread shutdown but that is fine
except KeyboardInterrupt:
    lcd.clear()
    led_ac.off()
    led_heat.off()
    led_light.off()
    print("Shutting down BMS")
