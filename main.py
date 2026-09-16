import collections
from enum import Enum, auto
from typing import List, Dict, Optional


class Syscall(Enum):
    PRINT = auto()
    ALLOC = auto()
    EXIT = auto()


class ProcessState(Enum):
    READY = auto()
    RUNNING = auto()
    TERMINATED = auto()


class PageTable:
    """Simulates hardware page translation with memory protection."""
    PAGE_SIZE = 64

    def __init__(self, num_frames: int = 16):
        self.physical_memory: bytearray = bytearray(num_frames * self.PAGE_SIZE)
        self.free_frames: List[int] = list(range(num_frames))
        self.mapping: Dict[int, int] = {}  # virtual_page -> physical_frame

    def allocate_page(self, v_page: int) -> int:
        if not self.free_frames:
            raise MemoryError("Out of physical memory frames!")
        p_frame = self.free_frames.pop(0)
        self.mapping[v_page] = p_frame
        return p_frame

    def translate(self, v_addr: int) -> int:
        v_page = v_addr // self.PAGE_SIZE
        offset = v_addr % self.PAGE_SIZE
        if v_page not in self.mapping:
            raise MemoryError(f"Page fault: unmapped virtual address 0x{v_addr:04X}")
        return (self.mapping[v_page] * self.PAGE_SIZE) + offset


class PCB:
    """Process Control Block: honest state tracking without shortcuts."""
    def __init__(self, pid: int, instructions: List[tuple]):
        self.pid: int = pid
        self.instructions: List[tuple] = instructions
        self.ip: int = 0  # Instruction Pointer
        self.registers: Dict[str, int] = {"r0": 0, "r1": 0}
        self.state: ProcessState = ProcessState.READY
        self.page_table: PageTable = PageTable()
        # Allocate initial code/data page
        self.page_table.allocate_page(0)


class Kernel:
    """Minimal OS kernel with scheduling, syscall dispatcher, and timer interrupt."""
    def __init__(self, time_slice: int = 2):
        self.process_queue: collections.deque[PCB] = collections.deque()
        self.current_process: Optional[PCB] = None
        self.time_slice: int = time_slice
        self.tick_counter: int = 0

    def add_process(self, instructions: List[tuple]) -> int:
        pid = len(self.process_queue) + (1 if not self.current_process else self.current_process.pid + 1)
        pcb = PCB(pid=pid, instructions=instructions)
        self.process_queue.append(pcb)
        print(f"[Kernel] Created Process PID={pid} with {len(instructions)} instructions")
        return pid

    def syscall(self, call_type: Syscall, arg1=None, arg2=None):
        """Hardware trap handling into privileged kernel mode."""
        proc = self.current_process
        if not proc:
            return

        if call_type == Syscall.PRINT:
            print(f"[Syscall:PRINT | PID {proc.pid}] {arg1}")
        elif call_type == Syscall.ALLOC:
            v_page = arg1
            try:
                p_frame = proc.page_table.allocate_page(v_page)
                print(f"[Syscall:ALLOC | PID {proc.pid}] Mapped VPage {v_page} -> Frame {p_frame}")
            except MemoryError as err:
                print(f"[Kernel Panic/Fault | PID {proc.pid}] {err}")
        elif call_type == Syscall.EXIT:
            print(f"[Syscall:EXIT | PID {proc.pid}] Process exiting.")
            proc.state = ProcessState.TERMINATED

    def schedule(self):
        """Round-Robin preemptive context switch."""
        if self.current_process and self.current_process.state == ProcessState.RUNNING:
            self.current_process.state = ProcessState.READY
            self.process_queue.append(self.current_process)

        if self.process_queue:
            self.current_process = self.process_queue.popleft()
            self.current_process.state = ProcessState.RUNNING
            print(f"[Context Switch] Now running PID {self.current_process.pid} (IP={self.current_process.ip})")
        else:
            self.current_process = None

    def step(self) -> bool:
        """Simulate one CPU clock tick."""
        if not self.current_process and not self.process_queue:
            return False

        if not self.current_process or self.current_process.state != ProcessState.RUNNING:
            self.schedule()
            if not self.current_process:
                return False

        proc = self.current_process
        if proc.ip >= len(proc.instructions):
            self.syscall(Syscall.EXIT)
            self.schedule()
            return True

        # Fetch & execute instruction
        op, *args = proc.instructions[proc.ip]
        proc.ip += 1
        self.tick_counter += 1

        if op == "SET":
            reg, val = args
            proc.registers[reg] = val
        elif op == "ADD":
            reg, val = args
            proc.registers[reg] += val
        elif op == "SYSCALL":
            self.syscall(args[0], *args[1:])
        elif op == "WRITE_MEM":
            v_addr, byte_val = args
            try:
                phys_addr = proc.page_table.translate(v_addr)
                proc.page_table.physical_memory[phys_addr] = byte_val
                print(f"[PID {proc.pid}] Memory write: virt 0x{v_addr:04X} -> phys 0x{phys_addr:04X} = {byte_val}")
            except MemoryError as e:
                print(f"[PID {proc.pid} Page Fault Trap] {e}")

        # Check timer interrupt / quantum expiration
        if proc.state == ProcessState.TERMINATED or self.tick_counter % self.time_slice == 0:
            self.schedule()

        return True

    def run(self):
        print("=== Starting Honest OS Kernel Execution ===")
        steps = 0
        while self.step():
            steps += 1
        print(f"=== System Halted. Total CPU cycles executed: {steps} ===")


if __name__ == "__main__":
    os_kernel = Kernel(time_slice=2)

    # Program 1: Counter and memory operations
    prog1 = [
        ("SET", "r0", 10),
        ("ADD", "r0", 5),
        ("SYSCALL", Syscall.PRINT, "Counter initialized"),
        ("WRITE_MEM", 0x0010, 42),  # Valid: page 0 is pre-allocated
        ("SYSCALL", Syscall.ALLOC, 1),  # Allocate page 1 (addresses 64-127)
        ("WRITE_MEM", 0x0045, 99),  # Valid: resides in virtual page 1
        ("WRITE_MEM", 0x0100, 77),  # Intentional invalid page access (triggers fault)
        ("SYSCALL", Syscall.EXIT),
    ]

    # Program 2: Interleaved task demonstrating cooperative multi-tasking
    prog2 = [
        ("SET", "r1", 100),
        ("SYSCALL", Syscall.PRINT, "Task 2 online"),
        ("ADD", "r1", 50),
        ("SYSCALL", Syscall.PRINT, "Task 2 completed computation"),
        ("SYSCALL", Syscall.EXIT),
    ]

    os_kernel.add_process(prog1)
    os_kernel.add_process(prog2)
    os_kernel.run()
