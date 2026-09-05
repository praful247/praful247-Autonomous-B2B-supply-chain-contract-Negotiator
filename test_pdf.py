from main import write_contract, ContractSchema

print("Generating mock contract to test PDF generation...")
mock_data = ContractSchema(final_price=1100, delivery_days=35)
result = write_contract(mock_data)
print("Contract generated successfully!")
print(result)
