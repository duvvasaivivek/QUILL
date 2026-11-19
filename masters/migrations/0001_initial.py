import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Customer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=30, unique=True)),
                ('name', models.CharField(max_length=160)),
                ('customer_type', models.CharField(choices=[('RETAILER', 'Retailer'), ('DISTRIBUTOR', 'Distributor')], max_length=16)),
                ('gstin', models.CharField(blank=True, max_length=15)),
                ('address', models.TextField(blank=True)),
                ('state_name', models.CharField(max_length=60)),
                ('state_code', models.CharField(max_length=2)),
                ('credit_limit', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ('code',),
            },
        ),
        migrations.CreateModel(
            name='Item',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sku', models.CharField(max_length=40, unique=True)),
                ('name', models.CharField(max_length=120)),
                ('category', models.CharField(choices=[('RAW', 'Raw material'), ('PACK', 'Packaging material'), ('FG', 'Finished good')], max_length=8)),
                ('hsn_code', models.CharField(blank=True, max_length=12)),
                ('gst_rate', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=5)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ('sku',),
            },
        ),
        migrations.CreateModel(
            name='Supplier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=30, unique=True)),
                ('name', models.CharField(max_length=160)),
                ('gstin', models.CharField(blank=True, max_length=15)),
                ('address', models.TextField(blank=True)),
                ('state_name', models.CharField(max_length=60)),
                ('state_code', models.CharField(max_length=2)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ('code',),
            },
        ),
        migrations.CreateModel(
            name='Unit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=12, unique=True)),
                ('name', models.CharField(max_length=50)),
                ('category', models.CharField(choices=[('MASS', 'Mass'), ('VOLUME', 'Volume'), ('COUNT', 'Count')], max_length=12)),
                ('conversion_to_base', models.DecimalField(decimal_places=6, default=Decimal('1'), max_digits=14)),
                ('is_base_unit', models.BooleanField(default=False)),
            ],
            options={
                'ordering': ('category', 'code'),
            },
        ),
        migrations.CreateModel(
            name='PriceList',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('effective_from', models.DateField()),
                ('effective_to', models.DateField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='price_lists', to='masters.customer')),
            ],
            options={
                'ordering': ('-effective_from', 'name'),
            },
        ),
        migrations.CreateModel(
            name='Product',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pack_size', models.DecimalField(decimal_places=3, max_digits=12)),
                ('selling_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('is_active', models.BooleanField(default=True)),
                ('item', models.OneToOneField(limit_choices_to={'category': 'FG'}, on_delete=django.db.models.deletion.PROTECT, related_name='product', to='masters.item')),
                ('pack_size_unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='product_pack_sizes', to='masters.unit')),
            ],
            options={
                'ordering': ('item__name',),
            },
        ),
        migrations.CreateModel(
            name='BOM',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(default=1)),
                ('expected_output_quantity', models.DecimalField(decimal_places=3, max_digits=12)),
                ('is_active', models.BooleanField(default=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='boms', to='masters.product')),
            ],
            options={
                'ordering': ('product', '-version'),
            },
        ),
        migrations.AddField(
            model_name='item',
            name='base_unit',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='items', to='masters.unit'),
        ),
        migrations.CreateModel(
            name='BOMLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=3, max_digits=14)),
                ('bom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='masters.bom')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bom_lines', to='masters.item')),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bom_lines', to='masters.unit')),
            ],
            options={
                'ordering': ('item__sku',),
            },
        ),
        migrations.CreateModel(
            name='PriceListItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('price_list', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='masters.pricelist')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='price_entries', to='masters.product')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('price_list', 'product'), name='unique_price_per_product')],
            },
        ),
        migrations.AddConstraint(
            model_name='bom',
            constraint=models.UniqueConstraint(fields=('product', 'version'), name='unique_bom_product_version'),
        ),
        migrations.AddConstraint(
            model_name='bomline',
            constraint=models.UniqueConstraint(fields=('bom', 'item'), name='unique_item_per_bom'),
        ),
    ]
