import time

# 1. HASH TABLE (Dictionary): O(1) Average Lookup by SKU
def build_sku_hash_table(products):
    return {item["sku"].upper(): item for item in products}

def hash_lookup_with_telemetry(products, sku):
    start = time.perf_counter()
    table = build_sku_hash_table(products)
    result = table.get(sku.upper())
    elapsed_us = (time.perf_counter() - start) * 1_000_000
    telemetry = {
        "algorithm": "Hash Table Lookup",
        "complexity": "O(1)",
        "steps": 1,
        "time_us": round(elapsed_us, 2)
    }
    return result, telemetry

# 2. MERGE SORT: O(n log n) Divide-and-Conquer Sorting with Comparison Counter
def merge_sort_with_telemetry(items, key_name):
    stats = {"comparisons": 0}
    start = time.perf_counter()
    sorted_items = _merge_sort(items, key_name, stats)
    elapsed_us = (time.perf_counter() - start) * 1_000_000
    telemetry = {
        "algorithm": "Merge Sort",
        "complexity": "O(n log n)",
        "steps": stats["comparisons"],
        "time_us": round(elapsed_us, 2)
    }
    return sorted_items, telemetry

def _merge_sort(items, key_name, stats):
    if len(items) <= 1:
        return items
    mid = len(items) // 2
    left = _merge_sort(items[:mid], key_name, stats)
    right = _merge_sort(items[mid:], key_name, stats)
    return _merge(left, right, key_name, stats)

def _merge(left, right, key_name, stats):
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        stats["comparisons"] += 1
        left_val = left[i][key_name].lower() if isinstance(left[i][key_name], str) else left[i][key_name]
        right_val = right[j][key_name].lower() if isinstance(right[j][key_name], str) else right[j][key_name]
        if left_val <= right_val:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result

# 3. BINARY SEARCH: O(log n) Search by Exact Product Name
def binary_search_with_telemetry(products, target_name):
    start = time.perf_counter()
    sorted_list, _ = merge_sort_with_telemetry(products, "name")
    low, high = 0, len(sorted_list) - 1
    target = target_name.strip().lower()
    steps = 0
    found = None

    while low <= high:
        steps += 1
        mid = (low + high) // 2
        mid_val = sorted_list[mid]["name"].lower()
        if mid_val == target:
            found = sorted_list[mid]
            break
        elif mid_val < target:
            low = mid + 1
        else:
            high = mid - 1

    elapsed_us = (time.perf_counter() - start) * 1_000_000
    telemetry = {
        "algorithm": "Binary Search",
        "complexity": "O(log n)",
        "steps": steps,
        "time_us": round(elapsed_us, 2)
    }
    return found, telemetry