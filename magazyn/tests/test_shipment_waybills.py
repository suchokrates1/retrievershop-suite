from magazyn.services.shipment_waybills import (
    expand_carrier_waybill_variants,
    extract_waybills_from_shipment_details,
)


def test_expand_dhl_keeps_numeric_waybill_only():
    variants = expand_carrier_waybill_variants("30774980700", "DHL")
    assert variants == ["30774980700"]


def test_extract_waybills_from_orlen_shipment():
    details = {
        "packages": [
            {
                "waybill": "AD02MJHDL5",
                "transportingInfo": [{"carrierId": "ORLEN", "carrierWaybill": "2102413302196"}],
            }
        ],
        "additionalProperties": {
            "EXTERNAL_CARRIER_WAYBILL": "2102413302196",
            "FIRST_MILE_CARRIER": "ORLEN",
        },
    }
    assert extract_waybills_from_shipment_details(details) == [
        "AD02MJHDL5",
        "2102413302196",
    ]
