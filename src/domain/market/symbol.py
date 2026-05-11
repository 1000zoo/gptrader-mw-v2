from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    base_asset: str
    quote_asset: str

    def __post_init__(self) -> None:
        base_asset = self.base_asset.strip().upper()
        quote_asset = self.quote_asset.strip().upper()

        if not base_asset:
            raise ValueError("base_asset is required")
        if not quote_asset:
            raise ValueError("quote_asset is required")
        if base_asset == quote_asset:
            raise ValueError("base_asset and quote_asset must be different")

        object.__setattr__(self, "base_asset", base_asset)
        object.__setattr__(self, "quote_asset", quote_asset)

    @property
    def pair(self) -> str:
        return f"{self.base_asset}{self.quote_asset}"
