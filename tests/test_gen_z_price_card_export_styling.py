import os
import re
import pytest

def test_gen_z_price_list_html_styling():
    price_list_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'price_list.html')
    with open(price_list_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Check .inflow-spec-card.gen_z in price_list.html
    assert 'border-radius: 28px !important;' in content
    assert 'padding: 24px 26px 20px 26px !important;' in content
    assert 'aspect-ratio: 1 / 1 !important;' in content
    assert 'justify-content: space-between !important;' in content

    # 2. Check stage container is absolute positioned at 0, 0
    assert 'id="plBatchExportStageContainer" style="position: absolute; left: 0; top: 0;' in content

    # 3. Check renderOffscreenPriceCard handles gen_z
    assert "styleToUse === 'gen_z' || styleToUse === 'genz'" in content
    assert "cardEl.style.justifyContent = 'space-between'" in content
    assert "cardEl.style.borderRadius = '28px'" in content
    assert "cardEl.style.padding = '24px 26px 20px 26px'" in content

    # 4. Check captureItemToCanvas passes scroll-offset proof html2canvas options
    assert 'captureItemToCanvas' in content
    assert 'x: 0' in content
    assert 'y: 0' in content
    assert 'width: 680' in content
    assert 'height: 680' in content
    assert 'scrollX: 0' in content
    assert 'scrollY: 0' in content
    assert 'clonedContainer.style.position = \'absolute\'' in content

def test_gen_z_styles_css():
    css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'styles.css')
    with open(css_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check .inflow-spec-card.gen_z
    assert '.inflow-spec-card.gen_z' in content
    assert 'border-radius: 28px !important;' in content
    assert 'padding: 24px 26px 20px 26px !important;' in content

def test_catalog_and_detail_offscreen_containers():
    cat_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'catalog.html')
    with open(cat_path, 'r', encoding='utf-8') as f:
        cat_content = f.read()
    assert 'id="batchPriceCardStageContainer" style="position: absolute; left: 0; top: 0;' in cat_content
    assert '#cardContentGenZ' in cat_content

    detail_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'products', 'detail.html')
    with open(detail_path, 'r', encoding='utf-8') as f:
        detail_content = f.read()
    assert 'id="batchPriceCardStageContainerDetail" style="position: absolute; left: 0; top: 0;' in detail_content
    assert '#cardContentGenZDetail' in detail_content

def test_database_catalog_protection_and_zero_test_sos():
    from app import create_app
    from extensions import db
    from models import Product, SalesOrder

    app = create_app()
    with app.app_context():
        # Check products exist and are intact
        product_count = Product.query.count()
        assert product_count > 0, "Product catalog must remain intact"

        # Check for lingering test orders
        test_sos = SalesOrder.query.filter(
            db.or_(
                SalesOrder.order_number.ilike('%test%'),
                SalesOrder.order_number.ilike('%temp%'),
                SalesOrder.remarks.ilike('%test%')
            )
        ).all()
        assert len(test_sos) == 0, f"Found lingering test sales orders: {[so.order_number for so in test_sos]}"
