"""
AgentReady — Canonical Product Model.

Modello interno unico verso cui convergono tutti i connettori di ingestion
(WooCommerce, PrestaShop, CSV) e da cui divergono tutti gli exporter
(ACP feed, Google Merchant Center, MCP server).

Principi:
- Superset dei formati target: ogni campo richiesto da ACP 2026-04-17 o da
  Google Merchant Center ha un posto qui.
- I prezzi sono Decimal in unità maggiori (EUR 19.90), la conversione in
  minor units (1990) avviene solo negli exporter.
- Nessuna dipendenza dai formati esterni: gli exporter sono adapter
  usa-e-getta, il modello canonico è stabile.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class BarcodeType(str, Enum):
    gtin = "gtin"       # copre EAN-13/UPC/GTIN-14
    ean = "ean"
    upc = "upc"
    isbn = "isbn"
    mpn = "mpn"         # manufacturer part number


class Barcode(BaseModel):
    type: BarcodeType
    value: str

    @field_validator("value")
    @classmethod
    def strip_value(cls, v: str) -> str:
        return v.strip()


class Money(BaseModel):
    amount: Decimal = Field(..., ge=0, description="Unità maggiori, es. 19.90")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")

    def minor_units(self) -> int:
        """Converte in minor units ISO 4217 (assume 2 decimali: EUR/USD/GBP...)."""
        return int((self.amount * 100).to_integral_value())


class AvailabilityStatus(str, Enum):
    in_stock = "in_stock"
    out_of_stock = "out_of_stock"
    preorder = "preorder"
    backorder = "backorder"
    discontinued = "discontinued"


class Availability(BaseModel):
    available: bool = True
    status: AvailabilityStatus = AvailabilityStatus.in_stock
    quantity: Optional[int] = Field(None, ge=0)


class MediaType(str, Enum):
    image = "image"
    video = "video"
    model_3d = "model"


class Media(BaseModel):
    type: MediaType = MediaType.image
    url: HttpUrl
    alt_text: Optional[str] = None


class Category(BaseModel):
    value: str = Field(..., description="Percorso gerarchico, es. 'Casa > Cucina > Pentole'")
    taxonomy: Optional[str] = Field(None, description="es. 'google_product_category', 'merchant'")


class VariantOption(BaseModel):
    name: str   # es. "Colore"
    value: str  # es. "Rosso"


class Shipping(BaseModel):
    """Info spedizione — richieste da Merchant Center, opzionali in ACP."""
    country: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    price: Optional[Money] = None
    handling_days_max: Optional[int] = Field(None, ge=0)


class Variant(BaseModel):
    id: str = Field(..., min_length=1, description="SKU o id stabile della variante")
    title: str = Field(..., min_length=1)
    description_plain: Optional[str] = None
    url: Optional[HttpUrl] = None
    barcodes: list[Barcode] = Field(default_factory=list)
    price: Optional[Money] = None
    list_price: Optional[Money] = Field(None, description="Prezzo pieno se scontato")
    availability: Availability = Field(default_factory=Availability)
    condition: str = "new"
    options: list[VariantOption] = Field(default_factory=list)
    media: list[Media] = Field(default_factory=list)
    shipping: list[Shipping] = Field(default_factory=list)
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Attributi liberi machine-readable (materiale, peso, certificazioni...)",
    )


class Product(BaseModel):
    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    brand: Optional[str] = None
    description_plain: Optional[str] = None
    description_html: Optional[str] = None
    url: Optional[HttpUrl] = None
    categories: list[Category] = Field(default_factory=list)
    media: list[Media] = Field(default_factory=list)
    variants: list[Variant] = Field(..., min_length=1)

    @field_validator("variants")
    @classmethod
    def unique_variant_ids(cls, v: list[Variant]) -> list[Variant]:
        ids = [x.id for x in v]
        if len(ids) != len(set(ids)):
            raise ValueError("id di variante duplicati nello stesso prodotto")
        return v


class Catalog(BaseModel):
    """Radice: un catalogo merchant normalizzato."""
    seller_name: str
    seller_url: Optional[HttpUrl] = None
    default_currency: str = Field("EUR", pattern=r"^[A-Z]{3}$")
    products: list[Product] = Field(default_factory=list)

    @field_validator("products")
    @classmethod
    def unique_product_ids(cls, v: list[Product]) -> list[Product]:
        ids = [x.id for x in v]
        if len(ids) != len(set(ids)):
            raise ValueError("id di prodotto duplicati nel catalogo")
        return v
