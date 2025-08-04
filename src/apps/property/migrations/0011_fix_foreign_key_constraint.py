
# Generated manually to fix foreign key constraint issues

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('property', '0010_fix_foreign_keys_utf8mb4'),
    ]

    operations = [
        # Deshabilitar verificaciones de foreign keys temporalmente
        migrations.RunSQL(
            """
            SET FOREIGN_KEY_CHECKS = 0;
            """,
            reverse_sql="SET FOREIGN_KEY_CHECKS = 1;"
        ),
        
        # Verificar y eliminar restricción problemática si existe
        migrations.RunSQL(
            """
            SET @constraint_exists = (
                SELECT COUNT(*)
                FROM information_schema.TABLE_CONSTRAINTS 
                WHERE CONSTRAINT_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'reservation_reservation' 
                AND CONSTRAINT_NAME LIKE '%property_id%'
                AND CONSTRAINT_TYPE = 'FOREIGN KEY'
            );
            
            SET @constraint_name = (
                SELECT CONSTRAINT_NAME
                FROM information_schema.TABLE_CONSTRAINTS 
                WHERE CONSTRAINT_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'reservation_reservation' 
                AND CONSTRAINT_NAME LIKE '%property_id%'
                AND CONSTRAINT_TYPE = 'FOREIGN KEY'
                LIMIT 1
            );
            
            SET @sql = IF(@constraint_exists > 0, 
                CONCAT('ALTER TABLE reservation_reservation DROP FOREIGN KEY ', @constraint_name, ';'), 
                'SELECT "No foreign key constraint found";'
            );
            
            PREPARE stmt FROM @sql;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
            """,
            reverse_sql="-- No reverse needed"
        ),
        
        # Asegurar que ambas tablas usen utf8mb4_unicode_ci
        migrations.RunSQL(
            """
            ALTER TABLE property_property CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            ALTER TABLE reservation_reservation CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """,
            reverse_sql="""
            ALTER TABLE property_property CONVERT TO CHARACTER SET utf8 COLLATE utf8_general_ci;
            ALTER TABLE reservation_reservation CONVERT TO CHARACTER SET utf8 COLLATE utf8_general_ci;
            """
        ),
        
        # Recrear la restricción de llave foránea con collations compatibles
        migrations.RunSQL(
            """
            ALTER TABLE reservation_reservation 
            ADD CONSTRAINT reservation_reservation_property_id_fk 
            FOREIGN KEY (property_id) REFERENCES property_property(id) 
            ON DELETE CASCADE ON UPDATE CASCADE;
            """,
            reverse_sql="ALTER TABLE reservation_reservation DROP FOREIGN KEY IF EXISTS reservation_reservation_property_id_fk;"
        ),
        
        # Rehabilitar verificaciones de foreign keys
        migrations.RunSQL(
            """
            SET FOREIGN_KEY_CHECKS = 1;
            """,
            reverse_sql="SET FOREIGN_KEY_CHECKS = 0;"
        ),
    ]
