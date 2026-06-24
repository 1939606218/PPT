import time, requests, concurrent.futures, base64, struct, zlib

API_KEY  = "ms-4f9a1bbe-143d-4c0b-939e-780ccef04121"
ENDPOINT = "https://api-inference.modelscope.cn/v1/chat/completions"
LLM_MODEL = "Qwen/Qwen3.5-35B-A3B"
VL_MODEL  = "Qwen/Qwen3-VL-8B-Instruct"

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# 生成一个 1x1 红色像素的最小合法 PNG（base64）
def _make_tiny_png_b64():
    def png_chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw  = b"\x00\xff\x00\x00"          # filter=0, R=255, G=0, B=0
    idat = png_chunk(b"IDAT", zlib.compress(raw))
    iend = png_chunk(b"IEND", b"")
    return base64.b64encode(sig + ihdr + idat + iend).decode()

TINY_PNG = _make_tiny_png_b64()

def make_llm_payload():
    return {"model": LLM_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}

def make_vl_payload():
    return {
        "model": VL_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{TINY_PNG}"}},
            {"type": "text", "text": "这张图片是什么颜色？一个词回答。"}
        ]}],
        "max_tokens": 10,
    }

def one_request(idx, payload_fn):
    t0 = time.time()
    try:
        r = requests.post(ENDPOINT, headers=HEADERS, json=payload_fn(), timeout=30)
        return idx, r.status_code, time.time() - t0
    except Exception as e:
        return idx, str(e), time.time() - t0

def run_test(label, n, concurrency, payload_fn):
    print(f"\n=== {label} | n={n} 并发={concurrency} ===")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(one_request, i, payload_fn): i for i in range(n)}
        results = [f.result() for f in concurrent.futures.as_completed(futs)]
    for idx, code, cost in sorted(results):
        mark = " <<<429" if code == 429 else ""
        print(f"  #{idx+1}: HTTP {code}  {cost:.2f}s{mark}")
    elapsed = time.time() - t0
    cnt429 = sum(1 for _, c, _ in results if c == 429)
    print(f"  总耗时: {elapsed:.2f}s | 成功: {n-cnt429}/{n} | 429数: {cnt429}")
    return cnt429

print("=" * 55)
print("  魔塔社区 API QPS 测试")
print("=" * 55)

print("\n\n【文字模型】", LLM_MODEL)
run_test("文字 · 串行",    5,  1, make_llm_payload)
run_test("文字 · 并发2",  10,  2, make_llm_payload)
run_test("文字 · 并发5",  10,  5, make_llm_payload)
run_test("文字 · 并发10", 10, 10, make_llm_payload)

print("\n\n【VL视觉模型】", VL_MODEL)
run_test("VL · 串行",    5,  1, make_vl_payload)
run_test("VL · 并发2",   8,  2, make_vl_payload)
run_test("VL · 并发5",   8,  5, make_vl_payload)
run_test("VL · 并发8",   8,  8, make_vl_payload)
