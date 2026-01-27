"""
Repozytorium operacji na ProductSize.

Centralizuje wszystkie operacje CRUD na rozmiarach produktow.
"""
from __future__ import annotations

import logging
from typing import List, Optional, NamedTuple, Tuple

from sqlalchemy.orm import Session

from ..models import Product, ProductSize


logger = logging.getLogger(__name__)


class ProductSizeInfo(NamedTuple):
    """DTO z informacjami o rozmiarze produktu."""
    ps_id: int
    product_id: int
    name: str
    color: str
    size: str
    barcode: Optional[str]
    quantity: int = 0


class ProductSizeRepository:
    """Repozytorium dla operacji na ProductSize."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def find_by_id(self, product_size_id: int) -> Optional[ProductSize]:
        """Znajdz rozmiar produktu po ID."""
        return self.db.query(ProductSize).filter(ProductSize.id == product_size_id).first()
    
    def find_by_barcode(self, barcode: str) -> Optional[ProductSize]:
        """Znajdz rozmiar produktu po kodzie kreskowym (EAN)."""
        if not barcode:
            return None
        return self.db.query(ProductSize).filter(ProductSize.barcode == barcode).first()
    
    def find_by_product_and_size(
        self, 
        product_id: int, 
        size: str
    ) -> Optional[ProductSize]:
        """Znajdz rozmiar produktu po ID produktu i rozmiarze."""
        return (
            self.db.query(ProductSize)
            .filter(
                ProductSize.product_id == product_id,
                ProductSize.size == size
            )
            .first()
        )
    
    def get_info_by_barcode(self, barcode: str) -> Optional[ProductSizeInfo]:
        """Pobierz informacje o rozmiarze produktu po kodzie kreskowym."""
        if not barcode:
            return None
        result = (
            self.db.query(
                ProductSize.id.label("ps_id"),
                Product.id.label("product_id"),
                Product.name,
                Product.color,
                ProductSize.size,
                ProductSize.barcode,
                ProductSize.quantity,
            )
            .join(Product, ProductSize.product_id == Product.id)
            .filter(ProductSize.barcode == barcode)
            .first()
        )
        if result:
            return ProductSizeInfo(*result)
        return None
    
    def get_all_with_product_info(self) -> List[ProductSizeInfo]:
        """Pobierz wszystkie rozmiary z informacjami o produktach."""
        results = (
            self.db.query(
                ProductSize.id.label("ps_id"),
                Product.id.label("product_id"),
                Product.name,
                Product.color,
                ProductSize.size,
                ProductSize.barcode,
                ProductSize.quantity,
            )
            .join(Product, ProductSize.product_id == Product.id)
            .all()
        )
        return [ProductSizeInfo(*r) for r in results]
    
    def get_sizes_for_product(self, product_id: int) -> List[ProductSize]:
        """Pobierz wszystkie rozmiary dla danego produktu."""
        return (
            self.db.query(ProductSize)
            .filter(ProductSize.product_id == product_id)
            .order_by(ProductSize.size)
            .all()
        )
    
    def get_with_barcodes(self) -> List[Tuple[str, str, str, str, int]]:
        """Pobierz wszystkie rozmiary z niepustymi kodami kreskowymi.
        
        Returns:
            Lista tupli (barcode, product_name, product_color, size, quantity)
        """
        return (
            self.db.query(
                ProductSize.barcode,
                Product.name,
                Product.color,
                ProductSize.size,
                ProductSize.quantity,
            )
            .join(Product, ProductSize.product_id == Product.id)
            .filter(ProductSize.barcode.isnot(None))
            .filter(ProductSize.barcode != "")
            .all()
        )
    
    def get_out_of_stock_count(self) -> int:
        """Policz rozmiary z zerowym stanem magazynowym."""
        return (
            self.db.query(ProductSize)
            .filter(ProductSize.quantity == 0)
            .count()
        )
    
    def get_low_stock(self, max_quantity: int = 2) -> List[Tuple[ProductSize, Product]]:
        """Pobierz rozmiary z niskim stanem magazynowym.
        
        Args:
            max_quantity: Maksymalna ilosc uznawana za niski stan (domyslnie 2)
            
        Returns:
            Lista tupli (ProductSize, Product)
        """
        return (
            self.db.query(ProductSize, Product)
            .join(Product)
            .filter(ProductSize.quantity > 0, ProductSize.quantity <= max_quantity)
            .order_by(ProductSize.quantity.asc())
            .all()
        )
    
    def update_quantity(
        self, 
        product_id: int, 
        size: str, 
        delta: int
    ) -> bool:
        """Zaktualizuj ilosc dla danego rozmiaru.
        
        Args:
            product_id: ID produktu
            size: Rozmiar
            delta: Zmiana ilosci (dodatnia lub ujemna)
            
        Returns:
            True jesli aktualizacja sie powiodla, False w przeciwnym razie
        """
        ps = self.find_by_product_and_size(product_id, size)
        if not ps:
            logger.warning(
                "Product id %s size %s not found, quantity update skipped",
                product_id,
                size,
            )
            return False
        
        new_quantity = ps.quantity + delta
        if new_quantity < 0:
            logger.warning(
                "Cannot set negative quantity for product_id=%s size=%s",
                product_id,
                size,
            )
            return False
        
        ps.quantity = new_quantity
        return True
    
    def create(
        self,
        product_id: int,
        size: str,
        quantity: int = 0,
        barcode: Optional[str] = None,
    ) -> ProductSize:
        """Utworz nowy rozmiar produktu."""
        ps = ProductSize(
            product_id=product_id,
            size=size,
            quantity=quantity,
            barcode=barcode,
        )
        self.db.add(ps)
        return ps
    
    def delete(self, product_size: ProductSize) -> None:
        """Usun rozmiar produktu."""
        self.db.delete(product_size)
