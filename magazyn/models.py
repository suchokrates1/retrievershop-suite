from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    color = Column(String)
    sizes = relationship('ProductSize', back_populates='product', cascade='all, delete-orphan')

class ProductSize(Base):
    __tablename__ = 'product_sizes'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'))
    size = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    barcode = Column(String, unique=True)
    product = relationship('Product', back_populates='sizes')

class PrintedOrder(Base):
    __tablename__ = 'printed_orders'
    order_id = Column(String, primary_key=True)
    printed_at = Column(String)

class LabelQueue(Base):
    __tablename__ = 'label_queue'
    id = Column(Integer, primary_key=True)
    order_id = Column(String)
    label_data = Column(Text)
    ext = Column(String)
    last_order_data = Column(Text)

class PurchaseBatch(Base):
    __tablename__ = 'purchase_batches'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    size = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    purchase_date = Column(String, nullable=False)
