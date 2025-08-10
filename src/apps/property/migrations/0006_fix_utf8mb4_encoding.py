# Generated manually to fix charset encoding

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0005_property_off_temperature_pool_url_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            """
            SET FOREIGN_KEY_CHECKS = 0;
            ALTER TABLE property_property CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            ALTER TABLE property_profitpropertyairbnb CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            SET FOREIGN_KEY_CHECKS = 1;
            """,
            reverse_sql="""
            SET FOREIGN_KEY_CHECKS = 0;
            ALTER TABLE property_property CONVERT TO CHARACTER SET utf8 COLLATE utf8_unicode_ci;
            ALTER TABLE property_profitpropertyairbnb CONVERT TO CHARACTER SET utf8 COLLATE utf8_unicode_ci;
            SET FOREIGN_KEY_CHECKS = 1;
            """
        ),
    ]