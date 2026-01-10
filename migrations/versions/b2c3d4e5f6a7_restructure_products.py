"""Restructure products: name -> category, brand, series

Revision ID: b2c3d4e5f6a7
Revises: 61fadb7b9515
Create Date: 2026-01-10 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import re


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = '61fadb7b9515'
branch_labels = None
depends_on = None


def parse_product_name(name: str) -> tuple[str, str, str]:
    """Parse old product name into (category, brand, series).
    
    Examples:
    - "Szelki dla psa Truelove Front Line Premium" -> ("Szelki", "Truelove", "Front Line Premium")
    - "Smycz dla psa Truelove Active" -> ("Smycz", "Truelove", "Active")
    - "Pas bezpieczeństwa dla psa Truelove" -> ("Pas bezpieczeństwa", "Truelove", "")
    """
    name_lower = (name or "").lower()
    
    # Detect category
    category = "Szelki"  # default
    if "smycz" in name_lower:
        category = "Smycz"
    elif "pas" in name_lower and ("bezpiecz" in name_lower or "samochodow" in name_lower):
        category = "Pas bezpieczeństwa"
    elif "obroża" in name_lower:
        category = "Obroża"
    elif "szelki" in name_lower:
        category = "Szelki"
    
    # Detect brand (default Truelove)
    brand = "Truelove"
    known_brands = ["truelove", "julius-k9", "julius k9", "ruffwear", "hurtta"]
    for b in known_brands:
        if b in name_lower:
            brand = b.replace("-", " ").title()
            if brand.lower() == "truelove":
                brand = "Truelove"
            break
    
    # Detect series
    series = ""
    series_patterns = [
        ("front line premium", "Front Line Premium"),
        ("front-line premium", "Front Line Premium"),
        ("frontline premium", "Front Line Premium"),
        ("fron line premium", "Front Line Premium"),
        ("front line", "Front Line"),
        ("front-line", "Front Line"),
        ("frontline", "Front Line"),
        ("fron line", "Front Line"),
        ("active", "Active"),
        ("blossom", "Blossom"),
        ("tropical", "Tropical"),
        ("lumen", "Lumen"),
        ("amor", "Amor"),
        ("classic", "Classic"),
        ("neon", "Neon"),
        ("reflective", "Reflective"),
    ]
    
    for pattern, series_name in series_patterns:
        if pattern in name_lower:
            series = series_name
            break
    
    return category, brand, series


def upgrade():
    # Add new columns
    op.add_column('products', sa.Column('category', sa.String(), nullable=True))
    op.add_column('products', sa.Column('brand', sa.String(), nullable=True))
    op.add_column('products', sa.Column('series', sa.String(), nullable=True))
    
    # Get connection for data migration
    connection = op.get_bind()
    
    # Fetch all products
    result = connection.execute(sa.text("SELECT id, name FROM products"))
    products = result.fetchall()
    
    # Update each product with parsed values
    for product_id, name in products:
        category, brand, series = parse_product_name(name)
        
        connection.execute(
            sa.text(
                "UPDATE products SET category = :category, brand = :brand, series = :series WHERE id = :id"
            ),
            {
                "id": product_id,
                "category": category,
                "brand": brand,
                "series": series if series else None,
            }
        )
    
    # Make category and brand NOT NULL (with default for brand)
    # SQLite doesn't support ALTER COLUMN, so we need to do this differently
    # For now, keep them nullable - we'll handle this in the model
    
    # Drop old name column (SQLite requires table recreation)
    # We'll keep the name column for backward compatibility via property
    # op.drop_column('products', 'name')  # Skip this for SQLite compatibility


def downgrade():
    # Reconstruct name from category, brand, series
    connection = op.get_bind()
    
    result = connection.execute(
        sa.text("SELECT id, category, brand, series FROM products")
    )
    products = result.fetchall()
    
    for product_id, category, brand, series in products:
        parts = [category or "Szelki", "dla psa"]
        if brand:
            parts.append(brand)
        if series:
            parts.append(series)
        name = " ".join(parts)
        
        connection.execute(
            sa.text("UPDATE products SET name = :name WHERE id = :id"),
            {"id": product_id, "name": name}
        )
    
    # Drop new columns
    op.drop_column('products', 'series')
    op.drop_column('products', 'brand')
    op.drop_column('products', 'category')
