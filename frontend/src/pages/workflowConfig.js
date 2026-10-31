const select = (name, label, optionsPath, optionLabel) => ({ name, label, optionsPath, optionLabel })
const farmer = (name = 'farmer', label = 'Farmer', searchEndpoint = '/farmers/') => ({ name, label, type: 'farmer', searchEndpoint })
const farm = (name = 'farm', label = 'Farm') => ({
  ...select(name, label, '/farms/', 'farm_name'),
  dependsOn: 'farmer',
  autoSelectSingle: true,
  disabledWithout: 'farmer',
})
const number = (name, label, min = '0', required = true) => ({ name, label, type: 'number', min, step: '0.01', required })
const crop = { name: 'crop', label: 'Crop' }

export const workflowPages = {
  crops: {
    title: 'Crop Catalogue', endpoint: '/crops/',
    columns: [{ key: 'name', label: 'Crop' }, { key: 'category', label: 'Season category' }, { key: 'active', label: 'Active' }],
    forms: [{ key: 'crop', title: 'Add or update crop', fields: [
      { name: 'name', label: 'Crop name' },
      { name: 'category', label: 'Category', choices: [['SUMMER', 'Summer'], ['WINTER', 'Winter']] },
      { name: 'active', label: 'Active', type: 'checkbox', required: false },
    ] }],
  },
  programmes: {
    title: 'Programmes', endpoint: '/programmes/',
    seasonScoped: true,
    editAction: true,
    deleteAction: true,
    columns: [
      { key: 'name', label: 'Programme' }, { key: 'code', label: 'Code' }, { key: 'institution', label: 'Institution' },
      { key: 'crop', label: 'Crop' }, { key: 'season_name', label: 'Agricultural year' },
      { key: 'announced_hectares', label: 'Capacity (ha)' }, { key: 'total_allocated_hectares', label: 'Allocated (ha)' },
      { key: 'remaining_capacity', label: 'Remaining (ha)' }, { key: 'status', label: 'Status' },
    ],
    forms: [{ key: 'programme', title: 'Create programme', editable: true, editSubmitLabel: 'Update programme', editButtonLabel: 'Edit', fields: [
      { name: 'name', label: 'Name' }, { name: 'code', label: 'Code' },
      { ...select('season', 'Agricultural year', '/seasons/'), selectableOnly: true },
      { name: 'crop', label: 'Crop', optionsPath: '/crops/', optionLabel: 'name', optionValue: 'name', categoryFromSeason: true, activeOnly: true },
      { name: 'institution', label: 'Institution' }, number('announced_hectares', 'Capacity (ha)', '0'),
      { name: 'status', label: 'Status', required: false, choices: [['DRAFT', 'Draft'], ['OPEN', 'Open'], ['CLOSED', 'Closed'], ['ARCHIVED', 'Archived']] },
    ] }],
  },
  arda: {
    title: 'ARDA Requests', endpoint: '/arda-request-batches/', editAction: true, deleteAction: true,
    seasonScoped: true,
    activeSeasonOnly: true,
    eligibleEndpoint: '/farmers/eligible/',
    eligibleTitle: 'Subscription-eligible farmers',
    eligibleColumns: [
      { key: 'full_name', label: 'Farmer' }, { key: 'membership_number', label: 'Membership' },
      { key: 'national_id', label: 'National ID' }, { key: 'phone_primary', label: 'Phone' },
      { key: 'district_name', label: 'District' }, { key: 'subscription_status', label: 'Subscription' },
    ],
    columns: [
      { key: 'request_number', label: 'Request' }, { key: 'programme_name', label: 'Programme' },
      { key: 'season_name', label: 'Agricultural year' },
      { key: 'crop', label: 'Crop' }, { key: 'requested_hectares', label: 'Requested HA' },
      { key: 'allocated_hectares', label: 'Allocated HA' }, { key: 'available_hectares', label: 'Available HA' },
      { key: 'total_farmers', label: 'Farmers' },
    ],
    forms: [
      {
        key: 'batch',
        title: 'Create request batch',
        endpoint: '/arda-request-batches/',
        submitLabel: 'Create batch',
        editable: true,
        editSubmitLabel: 'Update request',
        editButtonLabel: 'Edit',
        preventDuplicateBy: ['programme', 'crop'],
        duplicateStatuses: ['PENDING', 'SUBMITTED', 'APPROVED'],
        duplicateMessage: 'An ARDA request for this programme and crop already exists for the selected season. Please edit the existing request instead.',
        fields: [
        select('programme', 'Programme', '/programmes/'),
        { name: 'crop', label: 'Crop', optionsPath: '/crops/', optionLabel: 'name', optionValue: 'name', categoryFromSeason: true, activeOnly: true, required: false },
        number('requested_hectares', 'Requested hectares', '0.01'),
      ],
        globalSeasonField: 'season',
      },
    ],
  },
  allocations: {
    title: 'Input Allocations', endpoint: '/input-allocations/',
    seasonScoped: true,
    columns: [
      { key: 'farmer_name', label: 'Farmer' }, { key: 'programme_name', label: 'Programme' }, { key: 'crop', label: 'Crop' },
      { key: 'input_name', label: 'Input' }, { key: 'quantity', label: 'Quantity' }, { key: 'hectares', label: 'Hectares' },
      { key: 'status', label: 'Status' },
    ],
    forms: [{ key: 'allocation', title: 'Allocate inputs to an approved farmer', fields: [
      farmer(), farm(),
      select('programme', 'Programme', '/programmes/'), select('input', 'Input', '/inputs/'), crop,
      number('hectares', 'Hectares', '0.01'), number('quantity', 'Quantity', '0.01'), { name: 'unit', label: 'Unit' },
    ] }],
  },
  production: {
    title: 'Farmer Production', endpoint: '/farmer-productions/',
    seasonScoped: true,
    columns: [
      { key: 'farmer_name', label: 'Farmer' }, { key: 'season_name', label: 'Season' }, { key: 'crop', label: 'Crop' },
      { key: 'contracted_hectares', label: 'Contracted ha' }, { key: 'planted_hectares', label: 'Planted ha' },
      { key: 'expected_yield', label: 'Expected yield' }, { key: 'actual_production', label: 'Actual production' },
      { key: 'crop_stage', label: 'Stage' }, { key: 'status', label: 'Status' },
    ],
    forms: [{ key: 'production', title: 'Record production', fields: [
      farmer(), farm(),
      select('season', 'Season', '/seasons/'), crop, number('contracted_hectares', 'Contracted hectares'),
      number('planted_hectares', 'Planted hectares'), { name: 'planting_date', label: 'Planting date', type: 'date', required: false },
      number('expected_yield', 'Expected yield'), number('actual_production', 'Actual production'),
      { name: 'crop_stage', label: 'Crop stage', required: false },
      { name: 'status', label: 'Status', required: false, choices: [['PENDING', 'Pending'], ['PLANTED', 'Planted'], ['HARVESTED', 'Harvested'], ['COMPLETED', 'Completed']] },
    ] }],
  },
  seasonalPlanting: {
    title: 'Seasonal Farmer Planting', endpoint: '/seasonal-planting-plans/',
    seasonScoped: true,
    columns: [
      { key: 'farmer_name', label: 'Farmer' }, { key: 'season_name', label: 'Season' }, { key: 'farm_name', label: 'Farm' },
      { key: 'summer_crop_name', label: 'Summer crop' }, { key: 'summer_hectares', label: 'Summer ha' },
      { key: 'winter_crop_name', label: 'Winter crop' }, { key: 'winter_hectares', label: 'Winter ha' },
      { key: 'total_planted_hectares', label: 'Total planted ha' }, { key: 'recommended_subscription_amount', label: 'Recommended subscription' },
    ],
    forms: [{ key: 'seasonal-planting', title: 'Record farmer planting for a season', fields: [
      farmer(), farm(),
      select('season', 'Season', '/seasons/'),
      { ...select('summer_crop', 'Summer crop', '/crops/', 'name'), category: 'SUMMER', required: false },
      number('summer_hectares', 'Summer hectares', '0', false),
      { ...select('winter_crop', 'Winter crop', '/crops/', 'name'), category: 'WINTER', required: false },
      number('winter_hectares', 'Winter hectares', '0', false),
      { name: 'notes', label: 'Notes', required: false },
    ] }],
  },
  deliveries: {
    title: 'GMB Deliveries', endpoint: '/deliveries/',
    seasonScoped: true,
    columns: [
      { key: 'farmer_name', label: 'Farmer' }, { key: 'gmb_depot', label: 'Depot' },
      { key: 'delivery_reference', label: 'Reference' }, { key: 'ticket_number', label: 'Ticket' },
      { key: 'tonnes', label: 'Tonnes' }, { key: 'value', label: 'Value' }, { key: 'delivery_date', label: 'Date' },
    ],
    forms: [{
      key: 'delivery',
      title: 'Record GMB delivery',
      recoveryPreview: true,
      globalSeasonField: 'season',
      fields: [
      farmer(), farm(),
      { name: 'season_label', label: 'Season', readOnly: true, fromSeason: true, omitFromPayload: true },
      { name: 'crop', label: 'Crop', optionsPath: '/crops/', optionLabel: 'name', optionValue: 'name', categoryFromSeason: true, activeOnly: true },
      { name: 'delivery_date', label: 'Delivery date', type: 'date' },
      { name: 'gmb_depot', label: 'GMB depot' },
      { name: 'delivery_reference', label: 'Delivery reference', required: false },
      { name: 'ticket_number', label: 'Ticket number', required: false },
      number('tonnes', 'Tonnes delivered', '0.01'),
      { name: 'price', label: 'Price per tonne', readOnly: true, previewKey: 'price_per_tonne', omitFromPayload: true },
      { name: 'outstanding_input_debt', label: 'Outstanding input debt', readOnly: true, previewKey: 'outstanding_input_debt', omitFromPayload: true },
      { name: 'expected_recovery_tonnes', label: 'Expected tonnes to recover', readOnly: true, previewKey: 'expected_recovery_tonnes', omitFromPayload: true },
      number('recovery_tonnes', 'Actual recovery tonnes from delivery', '0', false),
    ] }],
  },
  recovery: {
    title: 'Recovery', endpoint: '/input-debts/',
    seasonScoped: true,
    columns: [
      { key: 'farmer_name', label: 'Farmer' }, { key: 'programme_name', label: 'Programme' },
      { key: 'required_recovery_tonnes', label: 'Required t' }, { key: 'recovered_tonnes', label: 'Recovered t' },
      { key: 'outstanding_tonnes', label: 'Outstanding t' }, { key: 'recovery_percentage', label: 'Recovery %' },
      { key: 'status', label: 'Status' },
    ],
    forms: [{ key: 'debt', title: 'Record recovery position', fields: [
      farmer(), farm(),
      select('programme', 'Programme', '/programmes/'), crop, number('required_recovery_tonnes', 'Required tonnes'),
      number('recovered_tonnes', 'Recovered tonnes'),
    ] }],
  },
}
