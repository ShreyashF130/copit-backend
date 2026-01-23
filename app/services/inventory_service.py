from app.utils.whatsapp import send_whatsapp_message
from app.utils.state_manager import state_manager


async def handle_selection_drilldown(phone, text, current_data):
    """
    Handles the user's input for specs (e.g., 'Red', 'XL').
    """
    attrs = current_data.get("attributes", {})
    specs = attrs.get("specs", [])
    idx = current_data.get("current_spec_index", 0)
    
    # Validate Selection
    current_spec_obj = specs[idx]
    valid_options = [opt.strip().lower() for opt in current_spec_obj['options']]
    
    if text.strip().lower() not in valid_options:
        options_str = ", ".join(current_spec_obj['options'])
        send_whatsapp_message(phone, f"❌ Invalid choice. Please pick: {options_str}")
        return

    # Save Selection
    selected_value = next((o for o in current_spec_obj['options'] if o.lower() == text.strip().lower()), text)
    user_selections = current_data.get("user_selections", {})
    user_selections[current_spec_obj['name']] = selected_value
    
    # Check if more specs exist
    if idx + 1 < len(specs):
        # Ask Next Spec
        next_spec = specs[idx + 1]
        options_str = ", ".join(next_spec['options'])
        
        await state_manager.set_state(phone, {
            "user_selections": user_selections,
            "current_spec_index": idx + 1
        })
        send_whatsapp_message(phone, f"✅ Selected {selected_value}.\nNow select *{next_spec['name']}*:\n({options_str})")
    else:
        # All Specs Selected -> Find Variant Logic
        # Construct title to match (e.g., "Red / XL")
        variant_title = " / ".join(user_selections.values())
        
        # Find matching variant in JSON
        variants = attrs.get('variants', [])
        found_variant = next((v for v in variants if v['title'] == variant_title), None)
        
        final_price = float(found_variant['price']) if found_variant and float(found_variant['price']) > 0 else current_data['base_price']
        
        # Save Final State
        formatted_options = f"({variant_title})"
        await state_manager.set_state(phone, {
            "state": "awaiting_qty",
            "price": final_price,
            "selected_options": formatted_options
        })
        
        msg = f"✅ *Configuration Complete!*\nVariaton: {variant_title}\n💰 Price: ₹{final_price}\n\n🔢 *How many would you like?*"
        send_whatsapp_message(phone, msg)