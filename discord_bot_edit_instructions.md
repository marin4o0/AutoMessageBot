# Discord AutoMessageBot - Edit Functionality Implementation Guide

## Extended Context with Domain Expertise Requirements

You are implementing a message editing feature for an existing Discord AutoMessageBot that currently sends automated messages with configurable intervals and timers. This enhancement adds comprehensive editing capabilities accessible through an embed-based interface with button controls, specifically designed for Discord server administrators and moderators to modify scheduled message configurations after creation.

The implementation requires deep understanding of Discord.js interaction systems (buttons, select menus, modals), embed manipulation, permission validation, and state management for scheduled messages. Your expertise must encompass Discord API v14+ button components, modal forms, select menu interactions, role-based permission checking, and seamless integration with existing bot architecture without disrupting current scheduling functionality.

## Detailed Role with Implementation Specifications

You are a Discord Bot Developer implementing a production-ready message editing system that integrates with existing AutoMessageBot infrastructure. Your implementation must maintain code consistency with the existing codebase style, handle all edge cases gracefully, implement robust permission checking, and provide intuitive user experience through Discord's native interaction components.

Your solution combines button-based controls, select menu navigation, and modal form inputs to create a cohesive editing workflow. You maintain strict permission validation requiring @Admin or @Moderator roles, implement proper error handling for all user interactions, and ensure data persistence across bot restarts through the existing storage mechanism.

## Sequential Implementation Protocols

### 1. Permission System Enhancement

**Objective**: Add role-based permission checking for edit functionality

**Implementation Steps**:
1. Locate your existing permission checking function (or create new one)
2. Add function to validate if user has @Admin or @Moderator role:

```javascript
function hasEditPermission(member) {
    return member.roles.cache.some(role => 
        role.name === 'Admin' || role.name === 'Moderator'
    );
}
```

3. This function will be called before allowing any edit operations

### 2. Embed Button Addition

**Objective**: Add :pencil2: edit button to existing control embeds

**Implementation Steps**:
1. Locate where you create ActionRow with start/stop/delete buttons
2. Add the edit button to the existing ActionRow:

```javascript
const editButton = new ButtonBuilder()
    .setCustomId('edit_message')
    .setEmoji('✏️') // Discord :pencil2: emoji
    .setStyle(ButtonStyle.Secondary);
```

3. Add `editButton` to your ActionRow components array alongside existing buttons
4. Ensure the button appears in the order: [start, stop, delete, edit]

### 3. Edit Button Interaction Handler

**Objective**: Capture edit button clicks and validate permissions

**Implementation Steps**:
1. Add interaction handler for button with customId `edit_message`:

```javascript
if (interaction.customId === 'edit_message') {
    // Permission check
    if (!hasEditPermission(interaction.member)) {
        return interaction.reply({
            content: 'You need Admin or Moderator role to edit messages.',
            ephemeral: true
        });
    }
    
    // Show edit menu
    await showEditMenu(interaction);
}
```

2. Place this handler in your existing button interaction listener section

### 4. Edit Selection Menu Implementation

**Objective**: Create menu for choosing what to edit (content/interval/timer)

**Implementation Steps**:
1. Create the selection menu function:

```javascript
async function showEditMenu(interaction) {
    const selectMenu = new StringSelectMenuBuilder()
        .setCustomId('edit_select')
        .setPlaceholder('Select what to edit')
        .addOptions([
            {
                label: 'Message Content',
                description: 'Edit the message text',
                value: 'edit_content',
                emoji: '📝'
            },
            {
                label: 'Time Interval',
                description: 'Edit the interval between messages',
                value: 'edit_interval',
                emoji: '⏱️'
            },
            {
                label: 'Timer/Schedule',
                description: 'Edit the schedule settings',
                value: 'edit_timer',
                emoji: '📅'
            }
        ]);

    const row = new ActionRowBuilder().addComponents(selectMenu);

    await interaction.reply({
        content: 'What would you like to edit?',
        components: [row],
        ephemeral: true
    });
}
```

2. Add this function to your bot's utility functions section

### 5. Select Menu Interaction Handler

**Objective**: Handle menu selection and route to appropriate edit modal

**Implementation Steps**:
1. Add select menu interaction handler:

```javascript
if (interaction.customId === 'edit_select') {
    const selectedOption = interaction.values[0];
    const messageId = interaction.message.id; // Get message ID to edit
    
    switch(selectedOption) {
        case 'edit_content':
            await showContentEditModal(interaction, messageId);
            break;
        case 'edit_interval':
            await showIntervalEditModal(interaction, messageId);
            break;
        case 'edit_timer':
            await showTimerEditModal(interaction, messageId);
            break;
    }
}
```

2. Add this to your select menu interaction listener section

### 6. Content Edit Modal Implementation

**Objective**: Create modal form for editing message content

**Implementation Steps**:
1. Create the content edit modal function:

```javascript
async function showContentEditModal(interaction, messageId) {
    // Get current message content from your storage
    const currentContent = getStoredMessageContent(messageId);
    
    const modal = new ModalBuilder()
        .setCustomId(`content_modal_${messageId}`)
        .setTitle('Edit Message Content');

    const contentInput = new TextInputBuilder()
        .setCustomId('new_content')
        .setLabel('New Message Content')
        .setStyle(TextInputStyle.Paragraph)
        .setValue(currentContent || '')
        .setRequired(true);

    const row = new ActionRowBuilder().addComponents(contentInput);
    modal.addComponents(row);

    await interaction.showModal(modal);
}
```

2. Replace `getStoredMessageContent()` with your actual data retrieval method

### 7. Interval Edit Modal Implementation

**Objective**: Create modal form for editing time interval

**Implementation Steps**:
1. Create the interval edit modal function:

```javascript
async function showIntervalEditModal(interaction, messageId) {
    // Get current interval from your storage
    const currentInterval = getStoredInterval(messageId);
    
    const modal = new ModalBuilder()
        .setCustomId(`interval_modal_${messageId}`)
        .setTitle('Edit Time Interval');

    const intervalInput = new TextInputBuilder()
        .setCustomId('new_interval')
        .setLabel('Interval (in minutes)')
        .setStyle(TextInputStyle.Short)
        .setValue(currentInterval?.toString() || '')
        .setPlaceholder('e.g., 30')
        .setRequired(true);

    const row = new ActionRowBuilder().addComponents(intervalInput);
    modal.addComponents(row);

    await interaction.showModal(modal);
}
```

2. Replace `getStoredInterval()` with your actual data retrieval method

### 8. Timer Edit Modal Implementation

**Objective**: Create modal form for editing schedule/timer settings

**Implementation Steps**:
1. Create the timer edit modal function:

```javascript
async function showTimerEditModal(interaction, messageId) {
    // Get current timer settings from your storage
    const currentTimer = getStoredTimer(messageId);
    
    const modal = new ModalBuilder()
        .setCustomId(`timer_modal_${messageId}`)
        .setTitle('Edit Timer/Schedule');

    const timerInput = new TextInputBuilder()
        .setCustomId('new_timer')
        .setLabel('Timer Settings')
        .setStyle(TextInputStyle.Short)
        .setValue(currentTimer || '')
        .setPlaceholder('e.g., 14:30 or daily')
        .setRequired(true);

    const row = new ActionRowBuilder().addComponents(timerInput);
    modal.addComponents(row);

    await interaction.showModal(modal);
}
```

2. Replace `getStoredTimer()` with your actual data retrieval method
3. Adjust placeholder text to match your timer format

### 9. Modal Submit Handlers

**Objective**: Process modal submissions and update stored data

**Implementation Steps**:
1. Add modal submit handlers for all three types:

```javascript
// Content modal handler
if (interaction.customId.startsWith('content_modal_')) {
    const messageId = interaction.customId.split('_')[2];
    const newContent = interaction.fields.getTextInputValue('new_content');
    
    // Update your storage
    updateMessageContent(messageId, newContent);
    
    // Update the embed
    await updateEmbed(interaction, messageId);
    
    await interaction.reply({
        content: 'Message content updated successfully!',
        ephemeral: true
    });
}

// Interval modal handler
if (interaction.customId.startsWith('interval_modal_')) {
    const messageId = interaction.customId.split('_')[2];
    const newInterval = parseInt(interaction.fields.getTextInputValue('new_interval'));
    
    // Validate interval is a number
    if (isNaN(newInterval)) {
        return interaction.reply({
            content: 'Please enter a valid number for interval.',
            ephemeral: true
        });
    }
    
    // Update your storage
    updateInterval(messageId, newInterval);
    
    // Update the embed
    await updateEmbed(interaction, messageId);
    
    await interaction.reply({
        content: 'Interval updated successfully!',
        ephemeral: true
    });
}

// Timer modal handler
if (interaction.customId.startsWith('timer_modal_')) {
    const messageId = interaction.customId.split('_')[2];
    const newTimer = interaction.fields.getTextInputValue('new_timer');
    
    // Update your storage
    updateTimer(messageId, newTimer);
    
    // Update the embed
    await updateEmbed(interaction, messageId);
    
    await interaction.reply({
        content: 'Timer updated successfully!',
        ephemeral: true
    });
}
```

2. Replace update functions with your actual storage update methods
3. Add these handlers to your modal interaction listener section

### 10. Embed Update Function

**Objective**: Refresh embed display with new values after editing

**Implementation Steps**:
1. Create the embed update function:

```javascript
async function updateEmbed(interaction, messageId) {
    // Retrieve updated data from storage
    const messageData = getMessageData(messageId);
    
    // Get the original message
    const originalMessage = await interaction.channel.messages.fetch(messageId);
    
    // Create updated embed with new values
    const updatedEmbed = new EmbedBuilder()
        .setTitle('Automated Message Configuration')
        .setDescription(messageData.content)
        .addFields(
            { name: 'Interval', value: `${messageData.interval} minutes`, inline: true },
            { name: 'Timer', value: messageData.timer || 'Not set', inline: true }
        )
        .setColor('#00ff00')
        .setTimestamp();
    
    // Update the message with new embed
    await originalMessage.edit({
        embeds: [updatedEmbed],
        components: originalMessage.components // Keep existing buttons
    });
}
```

2. Adjust embed fields to match your existing embed structure
3. Replace `getMessageData()` with your actual data retrieval method

### 11. Error Handling Implementation

**Objective**: Handle edge cases and errors gracefully

**Implementation Steps**:
1. Wrap all interaction handlers in try-catch blocks:

```javascript
try {
    // Your interaction handling code
} catch (error) {
    console.error('Edit interaction error:', error);
    
    if (!interaction.replied && !interaction.deferred) {
        await interaction.reply({
            content: 'An error occurred while processing your edit. Please try again.',
            ephemeral: true
        });
    }
}
```

2. Add validation for:
   - Message exists in storage
   - User still has permissions
   - Valid input formats
   - Bot has permission to edit messages

### 12. Integration Points Summary

**Critical Integration Requirements**:

1. **Storage System**: Ensure your existing storage (JSON file, database, etc.) supports:
   - Retrieving message data by message ID
   - Updating individual fields (content, interval, timer)
   - Persisting changes across bot restarts

2. **Scheduler Integration**: After editing interval or timer:
   - Clear existing scheduled task for that message
   - Reschedule with new parameters
   - Maintain message ID consistency

3. **Required Imports**: Add to your imports section:
```javascript
const { 
    ButtonBuilder, 
    ButtonStyle, 
    StringSelectMenuBuilder, 
    ModalBuilder, 
    TextInputBuilder, 
    TextInputStyle,
    ActionRowBuilder,
    EmbedBuilder 
} = require('discord.js');
```

## Advanced Format Guidelines

### Code Style Consistency
- Match your existing code formatting (indentation, naming conventions)
- Use the same error handling patterns you currently employ
- Maintain consistent async/await usage throughout

### Message ID Tracking
- Ensure message IDs are consistently tracked across all components
- Use message ID in custom IDs for traceability: `edit_select_${messageId}`
- Store message metadata mapping to original scheduled message configuration

### Permission Validation Points
- Check permissions at button click (edit_message)
- Revalidate permissions before showing modals (security layer)
- Handle permission changes mid-interaction gracefully

### Ephemeral vs Public Responses
- All edit menus and modals: ephemeral (only visible to user)
- Embed updates: public (visible to all, shows current configuration)
- Error messages: ephemeral (prevents channel spam)

## Comprehensive Target Audience

**Primary Implementer**: You, as the bot developer, implementing this feature into your existing AutoMessageBot codebase with working knowledge of Discord.js and your current bot architecture.

**End Users**: Discord server administrators and moderators with @Admin or @Moderator roles who manage automated message scheduling and need to modify configurations after creation without deleting and recreating messages.

**Technical Context**: Discord.js v14+ environment with existing button interaction handling, embed systems, and message scheduling infrastructure already implemented and functional.

**Experience Level**: Intermediate Discord.js developer familiar with interactions API, comfortable integrating new handlers into existing event listeners, and capable of adapting provided code to existing architecture patterns.

## Error Handling Protocols

### Permission Failures
- Always check role presence before showing edit interfaces
- Provide clear feedback: "You need Admin or Moderator role to edit messages"
- Log permission denial attempts for server security monitoring

### Invalid Input Handling
- Validate interval is numeric and positive
- Validate timer format matches your expected format
- Validate content is not empty
- Provide specific error messages indicating what was invalid

### Missing Data Scenarios
- Handle cases where message ID doesn't exist in storage
- Gracefully handle deleted Discord messages
- Provide fallback values if data retrieval fails

### Interaction Timeout Management
- Discord modals expire after 15 minutes
- Handle expired interaction errors gracefully
- Prompt users to restart edit process if timeout occurs

## Quality Assurance Measures

### Testing Checklist
- [ ] Edit button appears alongside existing control buttons
- [ ] Only users with @Admin or @Moderator roles can access editing
- [ ] Selection menu displays all three options correctly
- [ ] Content modal opens with current content pre-filled
- [ ] Interval modal opens with current interval pre-filled
- [ ] Timer modal opens with current timer settings pre-filled
- [ ] Submitting content modal updates embed display
- [ ] Submitting interval modal updates embed display
- [ ] Submitting timer modal updates embed display
- [ ] Updated values persist after bot restart
- [ ] Scheduled messages apply updated configurations
- [ ] Invalid inputs are rejected with clear error messages
- [ ] Embed updates maintain existing button functionality

### Integration Verification
- Test with existing start/stop/delete functionality to ensure no conflicts
- Verify data storage format compatibility
- Confirm scheduler applies new intervals/timers correctly
- Test multiple concurrent edits to different messages

### Edge Case Testing
- User loses permissions mid-edit
- Message deleted while edit modal is open
- Bot loses permissions to edit messages
- Multiple users attempting to edit same message simultaneously
- Invalid data in storage (malformed JSON, missing fields)

## Implementation Priority Order

1. **Phase 1 - Button Integration**: Add edit button to embeds, implement permission check
2. **Phase 2 - Menu System**: Implement selection menu and routing logic
3. **Phase 3 - Modal Forms**: Create all three modal forms with current value pre-filling
4. **Phase 4 - Data Updates**: Implement storage update logic and embed refresh
5. **Phase 5 - Scheduler Integration**: Connect edits to existing scheduling system
6. **Phase 6 - Testing & Refinement**: Comprehensive testing with edge cases

**Critical Success Metric**: Administrators and moderators can click the :pencil2: button, select what to edit from a menu, modify the value in a modal form, and immediately see the updated configuration reflected in the embed without any additional steps or confirmation prompts.