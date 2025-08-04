
# Generated manually to fix charset encoding

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0005_property_off_temperature_pool_url_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE property_property CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
            reverse_sql="ALTER TABLE property_property CONVERT TO CHARACTER SET utf8 COLLATE utf8_unicode_ci;"
        ),
    ]
