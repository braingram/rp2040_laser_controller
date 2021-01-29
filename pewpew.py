import time
from machine import Pin
from rp2 import PIO, StateMachine, asm_pio


@asm_pio()
def cycler_prog():
    wrap_target()
    #irq(0)  # clr, wait, index = 0
    irq(clear, 0)
    irq(0)
    mov(x, isr)
    label("delay")
    jmp(x_dec, "delay")
    wrap()


class Cycler:
    def __init__(self):
        self.sm = StateMachine(0, cycler_prog, freq=1000000)
        self.set_rate(15)

    def hz_to_cycles(self, hz):
        n = int((1000000 // hz) - 3)
        if n < 0:
            raise Exception("Invalid cycler rate: ", hz)
        # print out actual rate
        actual_hz = 1000000 / (n + 3)
        print("Rate set to ", actual_hz, " hz")
        return n

    def set_rate(self, rate_hz):
        n = self.hz_to_cycles(rate_hz)
        if self.sm.active():
            self.sm.active(0)
        self.sm.put(n)
        self.sm.exec("irq(0)")  # set irq initially so lasers can wait for clear
        self.sm.exec("pull()")
        self.sm.exec("mov(isr, osr)")
        self.sm.active(1)


@asm_pio(set_init=rp2.PIO.OUT_LOW)
def camera_prog():
    wrap_target()
    # wait for irq [trigger] from laser sm
    irq(block, 1)
    set(pins, 1)  # set pin high
    mov(x, isr) # setup delay
    label("delay")
    jmp(x_dec, "delay")  # delay
    set(pins, 0)  # set pin low
    irq(1)  # reset irq
    wrap()


class Camera:
    def __init__(self, pin_base):
        self.sm = StateMachine(1, camera_prog, freq=1000000, set_base=Pin(pin_base))
        self.set_exposure(30)

    def set_exposure(self, exposure_us):
        if exposure_us < 4:
            raise Exception("Invalid camera exposure: ", exposure_us)
        if self.sm.active():
            self.sm.active(0)
        self.sm.put(exposure_us - 3)
        self.sm.exec("irq(1)")  # set irq initially so lasers can clear
        self.sm.exec("pull()")
        self.sm.exec("mov(isr, osr)")
        self.sm.active(1)


@asm_pio(set_init=(rp2.PIO.OUT_LOW, rp2.PIO.OUT_LOW))
def laser_prog():
    wrap_target()
    # wait for irq to be set (then clear it)
    #wait(1, irq, 0) # pol=1, source = b10[irq], index = 0
    irq(block, 0)  # wait for irq 0 to clear
    # delay pre-warmup
    mov(x, isr)
    label("delay")
    jmp(x_dec, "delay")
    # raise warm up pin, wait 10 us
    set(pins, 1) [9]
    set(pins, 0)
    # delay until camera exposure (10 us before trigger)
    # delay extra 140 - 11 - 11 = 32 * 3 + 22 cycles
    nop() [31]
    nop() [31]
    nop() [31]
    nop() [21]
    # trigger camera
    irq(clear, 1) [10]
    # send trigger pulse
    set(pins, 2) [9]
    set(pins, 0)
    wrap()


class Laser:
    def __init__(self, state_machine_index, pin_base, delay):
        if state_machine_index < 2:
            raise Exception(
                "Invalid Laser state_machine_index :", state_machine_index)
        self.sm = StateMachine(
            state_machine_index, laser_prog, freq=1000000, set_base=Pin(pin_base))
        self.set_delay(delay)

    def set_delay(self, n_us):
        if n_us < 1:
            raise Exception("Invalid Laser delay :", n_us)
        if self.sm.active():
            self.sm.active(0)
        self.sm.put(n_us - 1)
        # TODO set irq0 here to avoid initial trigger?
        self.sm.exec("pull()")
        self.sm.exec("mov(isr, osr)")
        self.sm.active(1)


# print out irq changes for debugging purposes
#PIO(0).irq(lambda pio: print(pio.irq().flags()))

# unmask irqs
machine.mem8[0x50200000 + 0x12c] |= 0x0F00

initial_delay = 100
camera = Camera(1)
laser0 = Laser(2, 2, initial_delay)
laser1 = Laser(3, 4, initial_delay + 300)
cycler = Cycler()


def set_state(active):
    for o in (cycler, laser0, laser1, camera):
        o.sm.active(active)


running = True
while running:
    cmd = input().strip()
    if len(cmd) == 0:
        continue
    if cmd[0] in 'hH':
        print("Help me...")
    elif cmd[0] == 'E':
        print("enable...")
        set_state(1)
    elif cmd[0] == 'D':
        print("disable...")
        set_state(0)
    elif cmd[0] in ('qQ'):
        print("quit...")
        running = False
        break
    elif cmd[0] == 'r':
        try:
            rate = float(cmd[1:])
        except ValueError as e:
            print("Failed to read rate: ", e)
        print("rate: ", rate, " hz")
        cycler.set_rate(rate)
    elif cmd[0] == 'e':
        try:
            exp = int(cmd[1:])
        except ValueError as e:
            print("Failed to read exposure: ", e)
        print("exposure: ", exp, " us")
        camera.set_exposure(exp)
    elif cmd[0] == 'd':
        try:
            delay = int(cmd[1:])
        except ValueError as e:
            print("Failed to read delay: ", d)
        if delay < 35:
            print("Invalid delay cannot be <35")
            continue
        print("delay: ", delay, " us")
        laser1.set_delay(initial_delay + delay)

set_state(0)
