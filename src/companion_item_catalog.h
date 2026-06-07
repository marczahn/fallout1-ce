#ifndef FALLOUT_COMPANION_ITEM_CATALOG_H_
#define FALLOUT_COMPANION_ITEM_CATALOG_H_

#include <cstddef>

namespace fallout {

static constexpr size_t kCompanionItemNameSize = 64;
static constexpr size_t kCompanionItemProtoIdSize = 64;

struct CompanionItemMetadata {
    int pid;
    int type;
    char protoId[kCompanionItemProtoIdSize];
    char name[kCompanionItemNameSize];
};

bool companionLookupItemMetadata(int pid, CompanionItemMetadata& outMetadata);

void companionResetItemCatalog();

} // namespace fallout

#endif /* FALLOUT_COMPANION_ITEM_CATALOG_H_ */
