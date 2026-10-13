import io
import logging
from flask import Blueprint, render_template, request, jsonify, send_file, redirect, url_for, flash
from services.csv_exchange import (
    DATA_TYPES_META,
    get_meta,
    generate_sample_csv,
    export_data_to_csv,
    preview_import_data,
    execute_import_data
)

logger = logging.getLogger('inflow.data_exchange')

data_exchange_bp = Blueprint('data_exchange', __name__)

@data_exchange_bp.route('/data/import')
def import_data():
    initial_type = request.args.get('type', 'product').lower()
    return render_template('data/import.html', 
                           data_types=DATA_TYPES_META,
                           initial_type=initial_type)


@data_exchange_bp.route('/data/import/preview', methods=['POST'])
def import_preview_api():
    try:
        data_type = request.form.get('data_type', 'product')
        has_headers = request.form.get('has_headers', '1') in ['1', 'true', 'on']
        import_mode = request.form.get('import_mode', 'keep').strip().lower()
        
        file = request.files.get('file')
        if not file or not file.filename:
            return jsonify({'success': False, 'message': 'Please select a CSV file to import.'}), 400

        content = file.read()
        res = preview_import_data(data_type, content, has_headers=has_headers, import_mode=import_mode)
        res['success'] = True
        return jsonify(res)
    except Exception as e:
        logger.error(f"Import preview error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f"Error analyzing CSV file: {str(e)}"}), 500


@data_exchange_bp.route('/data/import/execute', methods=['POST'])
def import_execute_api():
    try:
        import json
        data_type = request.form.get('data_type', 'product')
        has_headers = request.form.get('has_headers', '1') in ['1', 'true', 'on']
        import_mode = request.form.get('import_mode', 'keep').strip().lower()
        
        selected_orders_raw = request.form.get('selected_orders')
        selected_orders = None
        if selected_orders_raw:
            try:
                selected_orders = json.loads(selected_orders_raw)
            except Exception:
                selected_orders = [s.strip() for s in selected_orders_raw.split(',') if s.strip()]

        selected_rows_raw = request.form.get('selected_rows')
        selected_rows = None
        if selected_rows_raw:
            try:
                selected_rows = json.loads(selected_rows_raw)
            except Exception:
                selected_rows = [int(s.strip()) for s in selected_rows_raw.split(',') if s.strip().isdigit()]
        
        file = request.files.get('file')
        if not file or not file.filename:
            return jsonify({'success': False, 'message': 'Please select a CSV file to import.'}), 400

        content = file.read()
        res = execute_import_data(
            data_type, content, 
            has_headers=has_headers, 
            import_mode=import_mode,
            selected_orders=selected_orders,
            selected_rows=selected_rows
        )
        return jsonify(res)
    except Exception as e:
        logger.error(f"Import execution error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f"Import failed: {str(e)}"}), 500


@data_exchange_bp.route('/data/export')
def export_data():
    initial_type = request.args.get('type', 'sales_order').lower()
    return render_template('data/export.html', 
                           data_types=DATA_TYPES_META,
                           initial_type=initial_type)


@data_exchange_bp.route('/data/export/download')
def export_download():
    try:
        data_type = request.args.get('type', 'sales_order').lower()
        csv_bytes, filename = export_data_to_csv(data_type)
        
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype='text/csv; charset=utf-8',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Export download error: {e}", exc_info=True)
        flash(f"Export failed: {str(e)}", 'error')
        return redirect(url_for('data_exchange.export_data'))


@data_exchange_bp.route('/data/template/<data_type>')
def download_template(data_type):
    try:
        csv_bytes, filename = generate_sample_csv(data_type)
        sample_name = f"Sample_{filename}"
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype='text/csv; charset=utf-8',
            as_attachment=True,
            download_name=sample_name
        )
    except Exception as e:
        logger.error(f"Template download error: {e}", exc_info=True)
        flash(f"Download template failed: {str(e)}", 'error')
        return redirect(url_for('data_exchange.import_data'))
