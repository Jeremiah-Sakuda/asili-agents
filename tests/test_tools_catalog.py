"""Tests for catalog tools."""

from asili_agents.tools.catalog import (
    catalog_search,
    check_stock,
    get_costs,
)


class TestCatalogSearch:
    """Tests for the catalog_search tool."""

    def test_search_by_name(self):
        """Test searching by product name."""
        results = catalog_search("purple tea")
        assert len(results) >= 1
        assert results[0]["name"] == "Purple Tea"

    def test_search_by_category(self):
        """Test searching by category."""
        results = catalog_search("specialty")
        assert len(results) >= 1
        # Should find Purple Tea (Specialty Tea category)

    def test_search_by_origin(self):
        """Test searching by origin."""
        results = catalog_search("Nandi Hills")
        assert len(results) >= 1
        # Should find Purple Tea and Silver Needle (both from Nandi Hills)

    def test_search_no_results(self):
        """Test search with no matches."""
        results = catalog_search("xyz-nonexistent-product")
        assert len(results) == 0

    def test_search_case_insensitive(self):
        """Test that search is case insensitive."""
        results_lower = catalog_search("purple")
        results_upper = catalog_search("PURPLE")
        assert len(results_lower) == len(results_upper)

    def test_search_result_structure(self):
        """Test that search results have correct structure."""
        results = catalog_search("tea")
        assert len(results) > 0

        result = results[0]
        assert "product_id" in result
        assert "sku" in result
        assert "name" in result
        assert "price" in result
        assert "in_stock" in result


class TestCheckStock:
    """Tests for the check_stock tool."""

    def test_check_stock_by_name(self):
        """Test checking stock by product name."""
        result = check_stock("Purple Tea")
        assert "error" not in result
        assert result["quantity"] == 6
        assert result["level"] == "low"
        assert result["is_available"] is True

    def test_check_stock_by_sku(self):
        """Test checking stock by SKU."""
        result = check_stock("MH-PRP-50")
        assert "error" not in result
        assert result["product_name"] == "Purple Tea"

    def test_check_stock_not_found(self):
        """Test checking stock for nonexistent product."""
        result = check_stock("nonexistent-product")
        assert "error" in result
        assert result["is_available"] is False

    def test_check_stock_result_structure(self):
        """Test that stock result has correct structure."""
        result = check_stock("Purple Tea")
        assert "product_id" in result
        assert "product_name" in result
        assert "quantity" in result
        assert "unit" in result
        assert "level" in result
        assert "low_threshold" in result
        assert "is_available" in result


class TestGetCosts:
    """Tests for the get_costs tool."""

    def test_get_costs_by_name(self):
        """Test getting costs by product name."""
        result = get_costs("Purple Tea")
        assert "error" not in result
        assert result["unit_cost"] == 7.40
        assert result["unit_price"] == 18.00

    def test_get_costs_margin(self):
        """Test that margin is calculated correctly."""
        result = get_costs("Purple Tea")
        # Margin = 18.00 - 7.40 = 10.60
        assert result["unit_margin"] == 10.60
        # Margin percent ≈ 0.589
        assert 0.58 < result["margin_percent"] < 0.60

    def test_get_costs_not_found(self):
        """Test getting costs for nonexistent product."""
        result = get_costs("nonexistent-product")
        assert "error" in result
