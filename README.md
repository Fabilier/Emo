# Emo Your Personal Companion Robot

<b>Hardware components:</b><br> 
<li>Raspberry Pi 4 Model B × 1</li>	
<li>Waveshare 2inch IPS LCD Display Module, 240×320 × 1</li>	
<li>SG90 Micro-servo motor × 2</li>	
<li>MG90 Servo Motor × 1</li>	
<li>PCA9685 - 16 Channel 12-Bit PWM Servo Motor Driver I2C Module × 1</li>	
<li>801S Vibration Shock Sensor Module × 1</li>	
<li>TTP223 1-Channel Capacitive Touch Sensor Module × 1</li>	
<li>Speaker: 0.5W 8 Ohm × 1</li>	
<li>PAM8403 5V 2-Channel Stereo Audio Amplifier Module × 1</li>	
<li>5x7 cm Double Sided Universal PCB Prototype Board × 1</li>	
<li>1x40 Pin 2.54mm Pitch Female Berg Strip Connector - Break Away Header - Straight × 1</li>	
<li>SS 304 CSK Countersunk Philips Head M2 X 10 mm Bolt – 10 Pieces pack × 1</li>	
<li>M3 x 10mm CHHD Bolt and Nut Set - 10 Pieces pack × 1</li>	
<li>M3 X 20mm CHHD Bolt and Nut Set -10 Piece pack × 1</li>	
<li>230m P/N B-30-1000 Insulated PVC Coated 30AWG Wire Wrapping Wire-RED × 1</li>	
<li>2mm Acrylic Sheet × 1</li>
<br> 
<br> 
https://www.hackster.io/coderscafe/emo-your-personal-companion-robot-dc8afe<br> 
https://www.instructables.com/Emo-DIY-Companion-Robot/

## Installation (Raspberry Pi)
```
sudo apt install alsa-utils python3-pip
pip install adafruit-circuitpython-servokit RPi.GPIO spidev pillow numpy
cd Code
python3 generate_sounds.py   # génère les .wav dans Code/sound
python3 final.py
```
Les chemins sont relatifs au dépôt : plus besoin de `/home/pi/Desktop/EmoBot`.
Sons : happy, sad, angry, excited, dizzy, bootup, blink (synthétisés, libres de droits).
