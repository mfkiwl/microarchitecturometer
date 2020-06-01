from itertools import count, cycle, islice

# Size config
loops = 10000
repeats = 10
test_sizes = range(0, 400, 2)

max_memory = 64 * 1024 * 1024
list_len = max_memory // 8 // repeats // 2

# Test configs
repeat = lambda n, instrs: "".join(islice(cycle(instrs), n))
asm = 'asm volatile(""{} : "+r"(r0), "+r"(r1), "+r"(r2), "+r"(r3), "+r"(r4), "+r"(r5), "+r"(list_0), "+r"(list_1) :: "cc");'.format
work_loop = 1024
store_buffer_size = 1

# Generally you want to use the first of these, but the others can potentially be more consistent
work = "list_{0} = (void **)*list_{0};"
# work = asm('"lzcnt %{0}, %{0}\\n"' * work_loop) # x86
# work = asm('"smulh %{0}, %{0}, %{0}\\n"' * work_loop) # aarch64
# work = asm('"clz %{0}, %{0}\\n"' * work_loop) # aarch64

# Test for ROB size
padding = lambda i: asm('"nop\\n"' * i)

# Tests for the number of rename registers — not exact for some reason
# padding = lambda i: asm(repeat(i, map('"mov %{0}, %{0}\\n"'.format, range(6))))
# padding = lambda i: asm(repeat(i, map('"cmp %{0}, %{0}\\n"'.format, range(6))))
# padding = lambda i: asm(repeat(i, map('"add %{0}, %{0}\\n"'.format, range(6)))) # x86
# padding = lambda i: asm(repeat(i, map('"add %{0}, %{0}, %{0}\\n"'.format, range(6)))) # aarch64

# Test for load buffer size
# padding = lambda i: asm(repeat(i, map('"mov (%{0}), %{0}\\n"'.format, range(6)))) # x86
# padding = lambda i: asm(repeat(i, map('"ldr %{0}, [%{0}]\\n"'.format, range(6)))) # aarch64

# Test for store buffer size
# store_buffer_size = max(test_sizes)
# padding = lambda i: asm(repeat(i, map('"mov %0, {}(%0)\\n"'.format, count(0, 8)))) # x86
# padding = lambda i: asm(repeat(i, map('"str %0, [%0, {}]\\n"'.format, count(0, 8)))) # aarch64



setup = """\
#include <inttypes.h>
#include <memory.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

__attribute__((noinline))
uint64_t get_nanos() {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return now.tv_sec * UINT64_C(1000000000) + now.tv_nsec;
}


// *Really* minimal PCG32 code / (c) 2014 M.E. O'Neill / pcg-random.org
// Licensed under Apache License 2.0 (NO WARRANTY, etc. see website)
typedef struct { uint64_t state;  uint64_t inc; } pcg32_random_t;

uint32_t pcg32_random_r(pcg32_random_t* rng)
{
    uint64_t oldstate = rng->state;
    rng->state = oldstate * 6364136223846793005ULL + (rng->inc|1);
    uint32_t xorshifted = ((oldstate >> 18u) ^ oldstate) >> 27u;
    uint32_t rot = oldstate >> 59u;
    return (xorshifted >> rot) | (xorshifted << ((-rot) & 31));
}

// Creates n_lists linked lists of length list_len,
// such that every n_lists'th element of mem is a member of a given list
void init_memory(void **mem, uint32_t list_len, uint32_t n_lists) {
    if (!list_len) {
        return;
    }

    pcg32_random_t rng = {0, 0};
    for (uint32_t i = 0; i < n_lists; ++i) {
        mem[i] = &mem[i];
    }
    for (uint32_t i = 1; i < list_len; ++i) {
        for (uint32_t j = 0; j < n_lists; ++j) {
            uint32_t k = pcg32_random_r(&rng) % i;
            mem[i * n_lists + j] = mem[k * n_lists + j];
            mem[k * n_lists + j] = &mem[i * n_lists + j];
        }
    }
}
"""

time_rob = """
__attribute__((noinline))
uint64_t time_rob_{variant}{n:06}(void **list_0, void **list_1) {{
    uint64_t start = get_nanos();

    uint64_t mem[{store_buffer_size}]; *mem = (uint64_t)mem;
    uint64_t r0 = *mem, r1 = *mem, r2 = *mem, r3 = *mem, r4 = *mem, r5 = *mem;
    _Pragma("nounroll")
    for (uint64_t i = 0; i < {loops}; ++i) {{
        {work_0}
        {padding}
        {work_1}
        {padding}
    }}

    return get_nanos() - start;
}}
"""

main = """\
int main() {{
    void **mem = calloc({list_len} * {repeats} * 2, sizeof(void *));
    init_memory(mem, {list_len}, {repeats} * 2);

    uint64_t results[{n_results}] = {{0}};
    uint64_t results_baseline[{n_results}] = {{0}};

    for (uint32_t i = 0; i < {repeats}; ++i) {{
{run_tests}
    }}

    for (uint32_t i = 0; i < {repeats}; ++i) {{
{run_baseline_tests}
    }}

    printf("padding\ttime taken\ttime taken (baseline)\\n");
{print_results}
}}
"""




print(setup)

for size in test_sizes:
    print(time_rob.format(n=size, store_buffer_size=store_buffer_size, loops=loops, variant="",          work_0=work.format(0), work_1=work.format(1), padding=padding(size)))
    print(time_rob.format(n=size, store_buffer_size=store_buffer_size, loops=loops, variant="baseline_", work_0=work.format(0), work_1=work.format(0), padding=padding(size)))

run_tests = "".join(f"""\
        results[{idx}] += time_rob_{size:06}(mem + {2 * idx}, mem + {2 * idx + 1});
""" for idx, size in enumerate(test_sizes))

run_baseline_tests = "".join(f"""\
        results_baseline[{idx}] += time_rob_baseline_{size:06}(mem + {idx}, mem + {2 * idx + 1});
""" for idx, size in enumerate(test_sizes))

print_results = "".join(f"""\
    printf("{size}\t%" PRIu64 "\t%" PRIu64 "\\n", results[{idx}] / {repeats}, results_baseline[{idx}] / {repeats});
""" for idx, size in enumerate(test_sizes))

print(main.format(n_results=len(test_sizes), list_len=list_len, repeats=repeats, run_tests=run_tests, run_baseline_tests=run_baseline_tests, print_results=print_results))