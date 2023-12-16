# RotorHazard VRx Control for the ExpressLRS Backpack

> [!CAUTION]
> This plugin is still in developmental state. Please do not install this plugin for events unless you acknowledge the risk of unstable features being present. The two associated risks include:
>1. Unwanted text being left on pilots' OSD when it is expected to be removed
>2. Text not being added to pilots' OSD when it should be. 

> [!NOTE]
>The timeline for the first offical release of this plugin is currently dependent on the stability of the following items:
>- this plugin
>- a new [timer backpack](https://github.com/ExpressLRS/Backpack/pull/114)
>- the backpack for the HDZero goggles

This is a plugin being developed for the RotorHazard timing system with the following features: 
- [X] Send OSD messages to pilots using compatible equipment (such as the [HDZero goggles](https://www.youtube.com/watch?v=VXwaUoA16jc)) 
- [X] Allows for the race manager to start the race from their transmitter
- [ ] Automatically switching pilot's video channels and output power 

## Requirements

- RotorHazard v4.0.0+ is required to run the plugin
- A connected device that can run the ExpressLRS Backpack (e.g. a ELRS RX or any ESP82xx/ESP32)
    - Connections over USB or UART will both work

## Installing RH Plugin

To install, follow the instructions on the [latest release](https://github.com/i-am-grub/VRxC_ELRS/releases) of the plugin.

## Hardware Installation / Setup

Please refer to the section that matches your Hardware.
We recommend the use of HDZero Goggles with ELRS Backpack since it offers the most functionalities in regards to OSD handling for the plugin.

All Hardware options will show all information but depending on technical restrictions information might be displayed differently (MSP-OSD for example can only show one line of text, upto 16 characters at a time while HDZero Goggles with ELRS Backpack can show an infinite amount of characters at any position / row in the OSD)

### HDZero Goggles with ELRS Backpack

1. Use the ExpressLRS Configurator to generate the firmware file. It is important to use the following steps to force the overwrite of the default firmware on the goggles.
    1. Open the ExpressLRS Configurator
    2. Select the Backpack tab
    3. Select release `1.4.1`
    4. Select the `HDZero Goggles` category
    5. Select the `Built-in ESP32 Backpack`
    6. Select the `WIFI` Flashing Method
    7. Enter your bindphrase. You can **NOT** change this on backpack's configuration page.
    8. Select `Build` (do not use FLASH)

> [!IMPORTANT]
> If your goggles did not come with backpack firmware, you should follow [these instructions](https://www.expresslrs.org/hardware/backpack/hdzero-goggles/) instead of continuing with listed installation instructions

2. Start the Backpack's Wifi (the the goggle's wifi)
3. Connect your computer to the backpack's wifi and open the backpack's configuration page.
    - If you haven't used it before, the webpage is similar to the default ExpressLRS configuration page.
4. Upload the generated file (e.g. `firmware.bin`) through the configuration page. If it show a warning about overwriting the previous firmware because it has a different name, force the overwrite.

### Betaflight Craftname

this uses the Betaflight Craftname to display racetimer information, therefore it is possible to use this with ANY video system that supports the Betaflight Craftname Element, including but not restricted to Walksnail, DJI V1, DJI V2, DJI O3, Analog.

In order to use this, please activate the Craftname element in your betaflight Configurator and place it somewhere visible in your OSD.

Since ELRS did not yet support setting the Betaflight Craftname we had to open a PR to enable this functionality. This is currently under review, therefore you need to install a "Beta" Version of ELRS on your ELRS Trasnmitter as well as on the ELRS Backpack that is connected to your ELRS Transmitter.

As soon as these PR's get merged / become part of the main source code of ELRS we will update this documentation.

In order to install the "beta" versions, follow the following steps:

#### Update your ELRS Transmitter Firmware

1. open the ExpressLRS Configurator
2. at the very top select "GIT PULL REQUEST"
3. select the Pull request with the following name: "Transmit Betaflight MSP "SET_NAME" packets from tx to fc #2504"
4. configure and flash your elrs transmitter as usual (Wifi or Cable, everything as usual ^^)

#### Update your ELRS Transmitter Backpack Firmware

1. open the ExpressLRS Configurator
2. on the left, select the tab called "Backpack"
3. at the very top select "GIT PULL REQUEST"
4. select the Pull request with the following name: "Passthrough for Betaflight MSP SET_NAME commands #123"
5. configure and flash your elrs transmitters backpack as usual (Wifi or Cable, everything as usual ^^)

## Control the Race from the Race Director's Transmitter

There is a feature to control the race from the Race Director's transmitter by tracking the position of the `DVR Rec` switch setup within the ransmitter's backpack. Currently only starting and stopping the race are supported.

> [!IMPORTANT]
> This feature requires the Race Director to have the ELRS Backpack setup on their transmitter. Please ensure this is setup before completing the following instructions.

1. Setup the `DVR Rec` switch in the ELRS backpack
    1. Open the ExpressLRS Lua script (v3 is recommended) on the transmitter
    2. Open up the Backpack settings
    3. Set the AUX channel for `DVR Rec`

> [!NOTE]
> Note: This will not not stop the ability to start recording DVR through this switch. It is just a state that the race timer's backpack listens for.

> [!CAUTION]
> It is recommended to not use the same AUX channel as your ARM switch. 

2. Bind the Race Timer backpack to the Transmitter
    1. Start the RotorHazard server with the ESP32 connected.
    2. Navigate to the `ELRS Backpack General Settings` panel.
    3. Click the `Start Backpack Bind` button.
    4. Within the ExpressLRS Lua script on the transmitter, click `Bind`

To test to see if the backpack was bound sucessfully, navigate the the `Race` tab within RotorHazard, and use the `DVR Rec` switch to start the race. `Race Control from Transmitter` will need to be enabled under `ELRS Backpack General Settings`

> [!TIP]
> Anytime the backpack needs to be bound to a new transmitter, it will be easiest to reflash the ESP32 with the firmware in the latest release, and then rebind. Attempting to rebind after the 

## Settings

### Pilot Settings

![Pilot Settings](docs/pilot_atts.png)

#### ELRS VRx Hardware : SELECTOR

Select the type of hardware that the pilot is using. To turn off OSD messages for a pilot, leave this option blank or set to `NONE`. In the graphic showing the pilot settings at the start of this section, Pilot 1 and Pilot 2 have OSD messages enabled - all other pilots have the option disabled

> [!TIP]
> Less pilots with OSD messages turned on means less delay is present for pilots with OSD messages turned on.

#### Backpack Bindphrase : TEXT

The pilot's individual bindphrase for their backpack. If a bindphrase is not set, the pilot's callsign will be used as the bindphrase instead.

### General Settings

![General Settings](docs/general_settings.png)

#### Race Control from Transmitter : CHECKBOX

Toggles the ability for the bound transmitter to start a race. Please navigate to [here](https://github.com/i-am-grub/VRxC_ELRS#control-the-race-from-the-race-directors-transmitter) for binding the backpack.

#### Number of times to repeat messages : INT

A setting to help with dropped packets. This setting determines the number of times a message should be repeated every time it is sent.

> [!IMPORTANT]
> It is advised that the Race Director should try to find the values that work best for their group. Inceasing the number may help with dropped packets, but will decrease ideal peformance. This setting will likely be removed in the first full release of the plugin. 

> [!TIP]
> this setting should be tuned to be as low as possible.

#### Send delay between messages : INT

A setting to help with dropped packets. This setting determines the speed at which the backpack sends messages.

> [!IMPORTANT]
> It is advised that the Race Director should try to find the values that work best for their group. Inceasing the number may help with dropped packets, but will decrease ideal peformance. This setting will likely be removed in the first full release of the plugin.

> [!TIP]
> this setting should be tuned to be as low as possible.

#### Start Backpack Bind : BUTTON

Puts the timer's backpack into a binding mode for pairing with the race director's transmitter.

> [!TIP]
> After sucessfully completing this process, the timer's backpack will inherit the race director's bindphrase from the transmitter.

#### Test Bound Backpack's OSD : BUTTON

Will display OSD messages on HDZero goggles with a matching bindphrase. Used for testing if the timer's backpack sucessfully inherited the transmitter's bindphrase.

#### Start Backpack WiFi : BUTTON

Starts the backpack's WiFi mode. Used for over-the-air firmware updates.

### OSD Settings

![OSD Settings](docs/osd_settings.png)

#### Show Race Name on Stage : CHECKBOX

Shows the race name on start.

> [!NOTE]
> Requires the race's class and heat names to be set

#### Show Current Position and Lap : CHECKBOX

- TOGGLED ON: Only shows current lap
- TOGGLED OFF: Shows current position and current lap when multiple pilots are in a race

#### Show Gap Time : CHECKBOX

- TOGGLED ON: Shows lap result time
- TOGGLED OFF: Shows the gap time to next pilot

#### Show Post-Race Results : CHECKBOX

The pilot will be shown results when they finish the race. It is recommeded to turn off `Post Flight Results` in Betaflight so the results won't be overridden when the pilot lands.

> [!NOTE]
> Rows 10-14 in the HDZero goggle's OSD are used by this feature

#### Race Stage Message : TEXT

The message shown to pilots when the timer is staging the race

#### Race Start Message : TEXT

The message shown to pilots when the race first starts

#### Pilot Done Message : TEXT

The message shown to pilots when the pilot finishes

#### Race Finish Message : TEXT

The message shown to pilots when the time runs runs out

#### Race Stop Message : TEXT

The message shown to pilots when the the race is stopped

#### Race Leader Message : TEXT

The message shown to pilots when `Show Gap Time` is enabled and the pilot is leading the race

#### Start Message Uptime : INT

The length of time `Race Start Message` is shown to pilots

#### Finish Message Uptime : INT

The length of time `Pilot Done Message` and `Race Finish Message` is shown to pilots

#### Lap Result Uptime : INT

Length of time the pilot's lap or gap time is shown after completing a lap. 

#### Announcement Uptime : INT

Length of time to show announcements to pilots. (e.g. When a race is scheduled)

#### Race Status Row : INT

Row to show race status messages.

> [!NOTE]
> Rows 10-14 are used by `Show Post-Race Results` when it is enabled. You can use these rows if the feature is disabled.

#### Current Lap/Position Row : INT

Row to show current lap and position

> [!NOTE]
> Rows 10-14 are used by `Show Post-Race Results` when it is enabled. You can use these rows if the feature is disabled.

#### Lap/Gap Results Row : INT

Row to show lap or gap time

> [!NOTE]
> Rows 10-14 are used by `Show Post-Race Results` when it is enabled. You can use these rows if the feature is disabled.

#### Announcement Row : INT

Row to show announcements such as when a race is scheduled. This row is also used by `Show Race Name on Stage`

> [!NOTE]
> Rows 10-14 are used by `Show Post-Race Results` when it is enabled. You can use these rows if the feature is disabled.