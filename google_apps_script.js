
/**
 * Google Apps Script para recibir datos de SearchTracking desde Django
 * y escribirlos en Google Sheets
 */

// Configuración
const SHEET_ID = 'TU_SHEET_ID_AQUI'; // Reemplaza con el ID de tu Google Sheet
const SHEET_NAME = 'SearchTracking'; // Nombre de la hoja donde se guardarán los datos

/**
 * Función principal que recibe las requests POST desde Django
 */
function doPost(e) {
  try {
    console.log('=== INICIO doPost ===');
    console.log('Content type:', e.postData.type);
    console.log('Raw data:', e.postData.contents);
    
    // Parsear datos JSON
    const data = JSON.parse(e.postData.contents);
    console.log('Parsed data:', data);
    
    // Verificar que sea una request de insert_search_tracking
    if (data.action === 'insert_search_tracking') {
      const result = insertSearchTrackingData(data.data);
      
      return ContentService
        .createTextOutput(JSON.stringify({
          success: true,
          message: 'Datos insertados correctamente',
          records_processed: result.records_processed,
          timestamp: new Date().toISOString()
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    // Para otras acciones o datos individuales
    const result = insertSingleRecord(data);
    
    return ContentService
      .createTextOutput(JSON.stringify({
        success: true,
        message: 'Registro individual insertado',
        record_id: result.record_id
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    console.error('Error en doPost:', error);
    
    return ContentService
      .createTextOutput(JSON.stringify({
        success: false,
        message: 'Error procesando datos: ' + error.toString(),
        timestamp: new Date().toISOString()
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Función para insertar múltiples registros de SearchTracking
 */
function insertSearchTrackingData(records) {
  try {
    console.log('Insertando', records.length, 'registros');
    
    // Abrir la hoja de cálculo
    const sheet = getOrCreateSheet();
    
    // Preparar headers si la hoja está vacía
    if (sheet.getLastRow() === 0) {
      const headers = [
        'ID', 'Timestamp Búsqueda', 'Check-in', 'Check-out', 'Huéspedes',
        'Cliente ID', 'Cliente Nombre', 'Cliente Apellido', 'Cliente Email', 'Cliente Teléfono',
        'Propiedad ID', 'Propiedad Nombre',
        'IP Address', 'Session Key', 'User Agent', 'Referrer', 'Fecha Creación'
      ];
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      
      // Formatear headers
      const headerRange = sheet.getRange(1, 1, 1, headers.length);
      headerRange.setFontWeight('bold');
      headerRange.setBackground('#e1f5fe');
    }
    
    // Preparar datos para insertar
    const rows = [];
    
    records.forEach(record => {
      const row = [
        record.id || '',
        record.search_timestamp || '',
        record.check_in_date || '',
        record.check_out_date || '',
        record.guests || '',
        record.client_info?.id || '',
        record.client_info?.first_name || '',
        record.client_info?.last_name || '',
        record.client_info?.email || '',
        record.client_info?.tel_number || '',
        record.property_info?.id || '',
        record.property_info?.name || '',
        record.technical_data?.ip_address || '',
        record.technical_data?.session_key || '',
        record.technical_data?.user_agent || '',
        record.technical_data?.referrer || '',
        record.created || ''
      ];
      rows.push(row);
    });
    
    // Insertar todas las filas de una vez
    if (rows.length > 0) {
      const startRow = sheet.getLastRow() + 1;
      sheet.getRange(startRow, 1, rows.length, rows[0].length).setValues(rows);
      console.log('Insertadas', rows.length, 'filas en Google Sheets');
    }
    
    return {
      records_processed: rows.length,
      sheet_name: SHEET_NAME
    };
    
  } catch (error) {
    console.error('Error insertando datos:', error);
    throw error;
  }
}

/**
 * Función para insertar un registro individual
 */
function insertSingleRecord(record) {
  try {
    console.log('Insertando registro individual:', record.id);
    
    const sheet = getOrCreateSheet();
    
    // Si la hoja está vacía, agregar headers
    if (sheet.getLastRow() === 0) {
      const headers = [
        'ID', 'Timestamp Búsqueda', 'Check-in', 'Check-out', 'Huéspedes',
        'Cliente ID', 'Cliente Nombre', 'Cliente Apellido', 'Cliente Email', 'Cliente Teléfono',
        'Propiedad ID', 'Propiedad Nombre',
        'IP Address', 'Session Key', 'User Agent', 'Referrer', 'Fecha Creación'
      ];
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    }
    
    // Preparar fila de datos
    const row = [
      record.id || '',
      record.search_timestamp || '',
      record.check_in_date || '',
      record.check_out_date || '',
      record.guests || '',
      record.client_info?.id || '',
      record.client_info?.first_name || '',
      record.client_info?.last_name || '',
      record.client_info?.email || '',
      record.client_info?.tel_number || '',
      record.property_info?.id || '',
      record.property_info?.name || '',
      record.technical_data?.ip_address || '',
      record.technical_data?.session_key || '',
      record.technical_data?.user_agent || '',
      record.technical_data?.referrer || '',
      record.created || ''
    ];
    
    // Insertar fila
    sheet.appendRow(row);
    
    return {
      record_id: record.id,
      sheet_name: SHEET_NAME
    };
    
  } catch (error) {
    console.error('Error insertando registro individual:', error);
    throw error;
  }
}

/**
 * Obtener o crear la hoja de SearchTracking
 */
function getOrCreateSheet() {
  try {
    const spreadsheet = SpreadsheetApp.openById(SHEET_ID);
    
    // Intentar obtener la hoja existente
    let sheet = spreadsheet.getSheetByName(SHEET_NAME);
    
    // Si no existe, crearla
    if (!sheet) {
      console.log('Creando nueva hoja:', SHEET_NAME);
      sheet = spreadsheet.insertSheet(SHEET_NAME);
    }
    
    return sheet;
    
  } catch (error) {
    console.error('Error accediendo a Google Sheet:', error);
    throw new Error('No se pudo acceder a Google Sheets. Verifica el SHEET_ID.');
  }
}

/**
 * Función de prueba para verificar que el script funciona
 */
function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({
      success: true,
      message: 'Google Apps Script webhook funcionando correctamente',
      timestamp: new Date().toISOString(),
      sheet_id: SHEET_ID,
      sheet_name: SHEET_NAME
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Función para limpiar datos antiguos (opcional)
 */
function cleanOldData(daysToKeep = 90) {
  try {
    const sheet = getOrCreateSheet();
    const data = sheet.getDataRange().getValues();
    
    if (data.length <= 1) return; // Solo headers o vacío
    
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - daysToKeep);
    
    // Filtrar filas que se deben mantener (más recientes que cutoffDate)
    const headers = data[0];
    const filteredData = [headers];
    
    for (let i = 1; i < data.length; i++) {
      const timestampStr = data[i][1]; // Columna de timestamp
      if (timestampStr) {
        const recordDate = new Date(timestampStr);
        if (recordDate >= cutoffDate) {
          filteredData.push(data[i]);
        }
      }
    }
    
    // Limpiar la hoja y escribir datos filtrados
    sheet.clear();
    if (filteredData.length > 0) {
      sheet.getRange(1, 1, filteredData.length, filteredData[0].length).setValues(filteredData);
    }
    
    console.log(`Limpieza completada. Registros mantenidos: ${filteredData.length - 1}`);
    
  } catch (error) {
    console.error('Error limpiando datos antiguos:', error);
    throw error;
  }
}
