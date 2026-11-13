# Adds the "txt" extraction method for plain-text documents.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="method",
            field=models.CharField(
                choices=[
                    ("", ""),
                    ("pdf_text", "pdf_text"),
                    ("pdf_ocr", "pdf_ocr"),
                    ("pdf_mixed", "pdf_mixed"),
                    ("docx", "docx"),
                    ("txt", "txt"),
                ],
                default="",
                max_length=16,
            ),
        ),
    ]
