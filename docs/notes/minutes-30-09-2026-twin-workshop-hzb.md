# Digital twin meeting


## Improvement requests

* Configuration needs to get better.
* Mark clearly PV's which are only provided by the twin
* improve documentation

## Requirements to Version 2.0

### From machine to machine complex

* For BESSSY II

   * Transfer line
   * Storage ring
   * ( inejection line to booster ?)
   * (booster)


The request was understood that calculation for the single machines was useful next to the total machine.

### Noisy data

Allow users to add noise to the data:

* add noise to the data of the beam position monitor
* 

### Devices

#### Pinholes

provide center position x,y and its size via sigma x, sigma y. Can already deliver
  much information. Extend it to draw images of the idealsed (Gaussian) beam profile derived
  from the Twiss parameters and a set emittance


####  Current and lifetime

This discussion raised different aspects:

* current pv and decay over time: needs to address topping up
* different current life times for the different bunches: here a
  user story seems to be missing: what these data need to provide
* current or sum pv for the beam position monitors: reflecting


#### Fill pattern

Would that be solely a single static variable.
Again a user story is missing.


#### Kickers

In conjunction with turn by turn data: injection kickers, extraction kickers (as part of the transfer line)

## Further requirements

### Time dependent behaviour of devices

Response of power converters to a new value set: ramp? overshoot? ringing?


## Turn by turn data

* track an ensemlbe of particles
* Provide output to BPM: center of mass and Sum like for the amount survived
* allow inserting arbitrary stops
* Handle fluresent screens: stop beam, or simply act as an observer
* fault injection for turn by turn data? (I have not more info noted, I'd appretiate if
  you, reader, could loop back to me if you know what is needed).
