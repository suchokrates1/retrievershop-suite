#!/usr/bin/env python3
"""Test what update_product returns."""

import sys
sys.path.insert(0, '/app')

from magazyn.domain.products import update_product

# Test update_product return value
product_id = 41

result = update_product(
    product_id=product_id,
    name="Test",
    color="Test",
    quantities={"S": 2, "XS": 0},
    barcodes={"S": "6971818794822", "XS": None},
    purchase_prices={}
)

print(f"Typ zwracanej wartości: {type(result)}")
print(f"Wartość: {result}")
print(f"Bool(result): {bool(result)}")
print(f"not result: {not result}")

if result:
    print(f"ID produktu: {result.id}")
    print(f"Nazwa: {result.name}")
